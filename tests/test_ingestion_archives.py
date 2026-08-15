from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path

import pandas as pd

from data_factory.ingestion.archives import iter_daily_archives
from data_factory.ingestion.models import Tolerance, UpdateError, UpdateStats
from data_factory.ingestion.sources.factor_database import _apply_daily_archive
from data_factory.ingestion.storage import StagingArea


def _empty_zip() -> bytes:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w"):
        pass
    return payload.getvalue()


class ArchiveTests(unittest.TestCase):
    def test_rejects_unrecognized_nested_zip(self) -> None:
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as outer:
            outer.writestr("notes.zip", _empty_zip())
        payload.seek(0)

        with (
            zipfile.ZipFile(payload) as outer,
            self.assertRaisesRegex(UpdateError, "无法识别的日包"),
        ):
            list(iter_daily_archives(outer))

    def test_rejects_duplicate_daily_dates(self) -> None:
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as outer:
            outer.writestr("a/factorDatabase_incre_pkl_20260801.zip", _empty_zip())
            outer.writestr("b/factorDatabase_incre_pkl_20260801.zip", _empty_zip())
        payload.seek(0)

        with (
            zipfile.ZipFile(payload) as outer,
            self.assertRaisesRegex(UpdateError, "重复日包日期"),
        ):
            list(iter_daily_archives(outer))

    def test_duplicate_target_is_rejected_before_staging(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            data.mkdir()
            target = data / "factor.pkl"
            frame = pd.DataFrame([[1.0]], index=[20260801], columns=["A"])
            pd.to_pickle(frame, target)
            pickle_payload = io.BytesIO()
            pd.to_pickle(frame, pickle_payload)

            daily_payload = io.BytesIO()
            with zipfile.ZipFile(daily_payload, "w") as daily:
                daily.writestr("one/factor.pkl", pickle_payload.getvalue())
                daily.writestr("two/factor.pkl", pickle_payload.getvalue())
            daily_payload.seek(0)

            staging = StagingArea(root / "staging", data)
            with (
                zipfile.ZipFile(daily_payload) as daily,
                self.assertRaisesRegex(UpdateError, "重复的目标文件名"),
            ):
                _apply_daily_archive(
                    daily,
                    "factorDatabase_incre_pkl_20260801.zip",
                    {"factor.pkl": target},
                    staging,
                    Tolerance(),
                    UpdateStats(),
                )
            self.assertEqual(len(staging), 0)


if __name__ == "__main__":
    unittest.main()
