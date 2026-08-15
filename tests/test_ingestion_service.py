from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path

import pandas as pd

from data_factory.ingestion import (
    Tolerance,
    UpdateConfig,
    UpdateError,
    update_dataset,
)

#: Bound once so it can serve as a default argument below.
_DEFAULT_TOLERANCE = Tolerance()


def _pickle_bytes(value: object) -> bytes:
    stream = io.BytesIO()
    pd.to_pickle(value, stream)
    return stream.getvalue()


class UpdateServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        root = Path(self._temporary.name)
        self.data = root / "data"
        self.delivery = root / "delivery"
        self.barra_dir = self.data / "barra"
        self.barra_dir.mkdir(parents=True)
        self.delivery.mkdir()

        dates = pd.date_range("2022-01-01", periods=1000, freq="D")
        date_values = pd.Series(dates.strftime("%Y%m%d").astype(int))
        self.local = pd.DataFrame(
            1.0, index=pd.Index(date_values.tolist()), columns=["A"]
        )
        pd.to_pickle(date_values, self.data / "trd_cal.pkl")
        pd.to_pickle(self.local, self.data / "factor.pkl")
        pd.to_pickle(self.local, self.barra_dir / "risk.pkl")

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def _write_barra(self, frame: pd.DataFrame) -> None:
        with zipfile.ZipFile(self.delivery / "barra.zip", "w") as archive:
            archive.writestr("risk.pkl", _pickle_bytes(frame))

    def _write_increment(self, frame: pd.DataFrame) -> None:
        inner_payload = io.BytesIO()
        with zipfile.ZipFile(inner_payload, "w") as inner:
            inner.writestr("factors/factor.pkl", _pickle_bytes(frame))
        archive_path = self.delivery / "factorDatabase_incre_pkl.zip"
        with zipfile.ZipFile(archive_path, "w") as outer:
            outer.writestr(
                "factorDatabase_incre_pkl_20260801.zip", inner_payload.getvalue()
            )

    def _config(
        self,
        *,
        delivery_dir: Path | None = None,
        tolerance: Tolerance = _DEFAULT_TOLERANCE,
        dry_run: bool = False,
        trusted_pickle: bool = True,
    ) -> UpdateConfig:
        return UpdateConfig(
            delivery_dir=delivery_dir or self.delivery,
            data_root=self.data,
            tolerance=tolerance,
            dry_run=dry_run,
            trusted_pickle=trusted_pickle,
        )

    def test_clean_delivery_can_be_confirmed_and_committed(self) -> None:
        changed_barra = self.local.copy()
        changed_barra.iloc[0, 0] = 2.0
        self._write_barra(changed_barra)
        self._write_increment(self.local)

        stats = update_dataset(self._config(), confirm=lambda _: "y")

        self.assertEqual(stats.error_count, 0)
        pd.testing.assert_frame_equal(
            pd.read_pickle(self.barra_dir / "risk.pkl"), changed_barra
        )
        pd.testing.assert_frame_equal(
            pd.read_pickle(self.data / "factor.pkl"), self.local
        )

    def test_error_prevents_confirmation_and_all_writes(self) -> None:
        changed_barra = self.local.copy()
        changed_barra.iloc[0, 0] = 2.0
        self._write_barra(changed_barra)
        inconsistent = self.local.copy()
        inconsistent.iloc[-1, 0] = 9.0
        self._write_increment(inconsistent)

        confirmations = 0

        def confirm(_: str) -> str:
            nonlocal confirmations
            confirmations += 1
            return "y"

        stats = update_dataset(self._config(), confirm=confirm)

        self.assertGreater(stats.error_count, 0)
        self.assertEqual(confirmations, 0)
        pd.testing.assert_frame_equal(
            pd.read_pickle(self.data / "factor.pkl"), self.local
        )
        pd.testing.assert_frame_equal(
            pd.read_pickle(self.barra_dir / "risk.pkl"), self.local
        )

    def test_dry_run_stages_without_writing(self) -> None:
        """通过校验也不落盘，哪怕交付内容确实和本地不同。"""
        changed_barra = self.local.copy()
        changed_barra.iloc[0, 0] = 2.0
        self._write_barra(changed_barra)
        self._write_increment(self.local)

        stats = update_dataset(self._config(dry_run=True), confirm=lambda _: "y")

        self.assertEqual(stats.error_count, 0)
        self.assertEqual(stats.barra_replaced, 1)
        pd.testing.assert_frame_equal(
            pd.read_pickle(self.barra_dir / "risk.pkl"), self.local
        )

    def test_minute_bars_take_no_part_in_the_update(self) -> None:
        """分钟行情是长表、按日一个文件，既不能按日期合并，也不由本模块交付。"""
        minute_dir = self.data / "market/bars/1m"
        minute_dir.mkdir(parents=True)
        long_format = pd.DataFrame(
            {"code": ["000001.SZ"], "date": [20260801], "close": [1.0]}
        )
        pd.to_pickle(long_format, minute_dir / "kline_day_20260801.pkl")
        self._write_barra(self.local)
        self._write_increment(self.local)

        stats = update_dataset(self._config(dry_run=True))

        self.assertEqual(stats.error_count, 0)

    def test_requires_explicit_pickle_trust(self) -> None:
        with self.assertRaisesRegex(UpdateError, "来源可信"):
            update_dataset(self._config(trusted_pickle=False))

    def test_rejects_invalid_tolerance(self) -> None:
        with self.assertRaisesRegex(UpdateError, "非负有限数"):
            update_dataset(self._config(tolerance=Tolerance(rtol=float("nan"))))

    def test_rejects_missing_delivery_directory(self) -> None:
        with self.assertRaisesRegex(UpdateError, "交付目录不存在"):
            update_dataset(self._config(delivery_dir=self.delivery / "nope"))


if __name__ == "__main__":
    unittest.main()
