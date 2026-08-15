from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from data_factory.ingestion.date_consistency import validate_recent_dates
from data_factory.ingestion.models import (
    DATE_CONSISTENCY_DAYS,
    MAX_DATE_LAG_DAYS,
    UpdateError,
)
from data_factory.ingestion.storage import StagingArea, build_catalog

#: Where the ingestion modules log; the handler-free package logger is what the
#: warning assertions listen on.
INGESTION_LOGGER = "data_factory.ingestion"


def _calendar(days: int) -> list[int]:
    """构造一段「交易日历」：取工作日，天然带着周末形成的间隔。"""
    dates = pd.bdate_range("2018-01-01", periods=days)
    return [int(value) for value in dates.strftime("%Y%m%d")]


class DateConsistencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.data = Path(self._temporary.name) / "data"
        self.data.mkdir()
        self.calendar = _calendar(DATE_CONSISTENCY_DAYS + 50)
        pd.to_pickle(pd.Series(self.calendar), self.data / "trd_cal.pkl")

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def _write_factor(self, dates: list[int], name: str = "factor.pkl") -> None:
        pd.to_pickle(
            pd.DataFrame(1.0, index=pd.Index(dates), columns=["A"]), self.data / name
        )

    def _validate(self) -> None:
        staging = StagingArea(self.data.parent / "staging", self.data)
        validate_recent_dates(build_catalog(self.data), staging)

    def test_exact_match_passes(self) -> None:
        self._write_factor(self.calendar)

        self._validate()

    def test_small_tail_lag_is_tolerated(self) -> None:
        """universe 这类文件本来就比行情晚一拍发布，不该判成错误。"""
        self._write_factor(self.calendar[:-1])

        with self.assertLogs(INGESTION_LOGGER, level="WARNING") as captured:
            self._validate()

        self.assertIn("落后 1 个交易日", "\n".join(captured.output))

    def test_tail_lag_beyond_limit_is_an_error(self) -> None:
        self._write_factor(self.calendar[: -(MAX_DATE_LAG_DAYS + 1)])

        with self.assertRaisesRegex(UpdateError, "落后"):
            self._validate()

    def test_hole_inside_covered_range_is_an_error(self) -> None:
        with_hole = self.calendar[:-10] + self.calendar[-9:]
        self._write_factor(with_hole)

        with self.assertRaisesRegex(UpdateError, "缺失 1 个交易日"):
            self._validate()

    def test_non_trading_day_is_an_error(self) -> None:
        self._write_factor(sorted([*self.calendar, self._non_trading_day()]))

        with self.assertRaisesRegex(UpdateError, "多出 1 个非交易日"):
            self._validate()

    def _non_trading_day(self) -> int:
        """校验窗口内的第一个非交易日（周末），用来伪造多余日期。"""
        known = set(self.calendar)
        candidate = pd.Timestamp(str(self.calendar[-DATE_CONSISTENCY_DAYS]))
        while int(candidate.strftime("%Y%m%d")) in known:
            candidate += pd.Timedelta(days=1)
        return int(candidate.strftime("%Y%m%d"))

    def test_short_history_is_not_reported_as_missing_dates(self) -> None:
        """起步晚的新因子不该因为没有更早的历史就被判为缺日期。"""
        self._write_factor(self.calendar[-30:])

        self._validate()

    def test_lag_message_does_not_point_at_unrelated_old_dates(self) -> None:
        """旧实现会把窗口错位报成几年前的「缺失/额外」，把排查带偏。"""
        self._write_factor(self.calendar[: -(MAX_DATE_LAG_DAYS + 1)])

        with self.assertRaises(UpdateError) as raised:
            self._validate()

        message = str(raised.exception)
        self.assertNotIn("2018", message)
        self.assertIn("落后", message)


if __name__ == "__main__":
    unittest.main()
