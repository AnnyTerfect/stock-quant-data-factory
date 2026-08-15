from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path

import pandas as pd

from data_factory.core.layout import minute_file_name
from data_factory.ingestion.models import (
    DATE_CONSISTENCY_DAYS,
    MINUTE_ARCHIVE_NAME,
    UpdateError,
    UpdateStats,
)
from data_factory.ingestion.sources import minute_bars
from data_factory.ingestion.storage import StagingArea, build_catalog

#: Where the ingestion modules log; the error assertions listen on it.
INGESTION_LOGGER = "data_factory.ingestion"


def _calendar(days: int) -> list[int]:
    """构造一段「交易日历」：取工作日，天然带着周末形成的间隔。"""
    dates = pd.bdate_range("2018-01-01", periods=days)
    return [int(value) for value in dates.strftime("%Y%m%d")]


def _minute_day(date: int, close: float = 1.0) -> pd.DataFrame:
    """一天的分钟长表：两只股票各两分钟。"""
    return pd.DataFrame(
        {
            "code": [1, 1, 2, 2],
            "date": [date] * 4,
            "time": [930, 931, 930, 931],
            "open": [1.0, 1.0, 2.0, 2.0],
            "high": [1.5, 1.5, 2.5, 2.5],
            "low": [0.5, 0.5, 1.5, 1.5],
            "close": [close] * 4,
            "volume": [100, 200, 300, 400],
            "amount": [1000.0, 2000.0, 3000.0, 4000.0],
        }
    )


class MinuteBarsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        root = Path(self._temporary.name)
        self.data = root / "data"
        self.minute_dir = self.data / "market/bars/1m"
        self.minute_dir.mkdir(parents=True)
        self.delivery = root / "delivery"
        self.delivery.mkdir()
        self.archive_path = self.delivery / MINUTE_ARCHIVE_NAME

        self.calendar = _calendar(DATE_CONSISTENCY_DAYS + 50)
        pd.to_pickle(pd.Series(self.calendar), self.data / "trd_cal.pkl")
        # The dataset already holds the recent trading days but the last two,
        # which is what one delivery brings. Only the recent ones are written:
        # a history that starts late is not a hole, so filling the whole
        # baseline window would cost a thousand files and check nothing more.
        self.local_days = self.calendar[-32:-2]
        self.delivered_days = self.calendar[-2:]
        for date in self.local_days:
            pd.to_pickle(_minute_day(date), self.minute_dir / minute_file_name(date))

        self.staging = StagingArea(root / "staging", self.data)
        self.stats = UpdateStats()

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def _write_archive(self, members: dict[str, object]) -> None:
        with zipfile.ZipFile(self.archive_path, "w") as archive:
            for name, value in members.items():
                stream = io.BytesIO()
                pd.to_pickle(value, stream)
                archive.writestr(name, stream.getvalue())

    def _write_days(self, days: dict[int, pd.DataFrame]) -> None:
        self._write_archive(
            {minute_file_name(date): frame for date, frame in days.items()}
        )

    def _update(self) -> None:
        minute_bars.update(
            archive_path=self.archive_path,
            minute_dir=self.minute_dir,
            catalog=build_catalog(self.data, skip=[self.minute_dir]),
            staging=self.staging,
            stats=self.stats,
        )

    def _staged(self, date: int) -> Path:
        target = self.minute_dir / minute_file_name(date)
        staged = self.staging.source_path(target)
        self.assertNotEqual(staged, target)
        return staged

    def test_new_days_are_staged_as_delivered(self) -> None:
        self._write_days({date: _minute_day(date) for date in self.delivered_days})

        self._update()

        self.assertEqual(self.stats.minute_days_added, 2)
        self.assertEqual(len(self.staging), 2)
        for date in self.delivered_days:
            pd.testing.assert_frame_equal(
                pd.read_pickle(self._staged(date)), _minute_day(date)
            )
        # Nothing is written until the service commits.
        for date in self.delivered_days:
            self.assertFalse((self.minute_dir / minute_file_name(date)).exists())

    def test_day_already_held_and_equal_is_skipped(self) -> None:
        """重复交付同一天是正常的，一致就不必再写一遍。"""
        repeated = self.local_days[-1]
        self._write_days({repeated: _minute_day(repeated)})

        self._update()

        self.assertEqual(self.stats.minute_days_added, 0)
        self.assertEqual(self.stats.minute_days_verified, 1)
        self.assertEqual(len(self.staging), 0)

    def test_row_order_alone_is_not_a_difference(self) -> None:
        """长表的行序不带信息，按行序判不一致会把真正的差异淹掉。"""
        repeated = self.local_days[-1]
        self._write_days({repeated: _minute_day(repeated).iloc[::-1]})

        self._update()

        self.assertEqual(self.stats.minute_days_verified, 1)

    def test_day_already_held_but_different_is_an_error(self) -> None:
        repeated = self.local_days[-1]
        self._write_days({repeated: _minute_day(repeated, close=9.0)})

        with self.assertLogs(INGESTION_LOGGER, level="ERROR") as captured:
            self._update()

        output = "\n".join(captured.output)
        self.assertIn("已有交易日与输入不一致", output)
        self.assertIn("close", output)
        self.assertEqual(len(self.staging), 0)

    def test_file_name_date_must_match_the_data(self) -> None:
        first, second = self.delivered_days
        self._write_days({first: _minute_day(second)})

        with self.assertLogs(INGESTION_LOGGER, level="ERROR") as captured:
            self._update()

        self.assertIn("文件名日期与数据日期不符", "\n".join(captured.output))
        self.assertEqual(self.stats.minute_days_added, 0)
        self.assertEqual(len(self.staging), 0)

    def test_missing_fields_are_an_error(self) -> None:
        date = self.delivered_days[0]
        self._write_days({date: _minute_day(date).drop(columns=["amount"])})

        with self.assertLogs(INGESTION_LOGGER, level="ERROR") as captured:
            self._update()

        self.assertIn("缺少字段", "\n".join(captured.output))
        self.assertEqual(len(self.staging), 0)

    def test_one_bad_day_does_not_stop_the_others(self) -> None:
        first, second = self.delivered_days
        self._write_days(
            {first: _minute_day(first).iloc[:0], second: _minute_day(second)}
        )

        with self.assertLogs(INGESTION_LOGGER, level="ERROR"):
            self._update()

        self.assertEqual(self.stats.minute_days_added, 1)
        self.assertTrue(self._staged(second).exists())

    def test_unrecognized_member_name_rejects_the_archive(self) -> None:
        """每个成员都该是一天行情；认不出来说明交付形态变了。"""
        self._write_archive({"kline_20260801.pkl": _minute_day(20260801)})

        with self.assertRaisesRegex(UpdateError, "命名规则"):
            self._update()

    def test_repeated_trading_day_rejects_the_archive(self) -> None:
        date = self.delivered_days[0]
        name = minute_file_name(date)
        self._write_archive(
            {name: _minute_day(date), f"nested/{name}": _minute_day(date)}
        )

        with self.assertRaisesRegex(UpdateError, "重复的交易日"):
            self._update()

    def test_empty_archive_is_rejected(self) -> None:
        self._write_archive({})

        with self.assertRaisesRegex(UpdateError, "没有任何分钟行情文件"):
            self._update()

    def test_missing_archive_is_rejected(self) -> None:
        with self.assertRaisesRegex(UpdateError, "找不到分钟行情压缩包"):
            self._update()

    def test_hole_against_the_calendar_is_an_error(self) -> None:
        """按日一个文件，漏掉一天不会被任何矩阵的日期轴发现。"""
        (self.minute_dir / minute_file_name(self.local_days[-1])).unlink()
        self._write_days({date: _minute_day(date) for date in self.delivered_days})

        with self.assertLogs(INGESTION_LOGGER, level="ERROR") as captured:
            self._update()

        self.assertIn("缺失 1 个交易日", "\n".join(captured.output))
        # The days themselves were fine, and stay staged for the summary to weigh.
        self.assertEqual(self.stats.minute_days_added, 2)

    def test_stale_tail_beyond_the_limit_is_an_error(self) -> None:
        for date in self.local_days[-6:]:
            (self.minute_dir / minute_file_name(date)).unlink()
        repeated = self.local_days[-7]
        self._write_days({repeated: _minute_day(repeated)})

        with self.assertLogs(INGESTION_LOGGER, level="ERROR") as captured:
            self._update()

        self.assertIn("落后", "\n".join(captured.output))


if __name__ == "__main__":
    unittest.main()
