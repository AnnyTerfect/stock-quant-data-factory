from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from data_factory.ingestion import storage as storage_module
from data_factory.ingestion.storage import StagingArea


class StagingTests(unittest.TestCase):
    def test_checkpoint_restores_previous_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            data.mkdir()
            target = data / "factor.pkl"
            pd.to_pickle("original", target)
            staging = StagingArea(root / "staging", data)

            staging.stage_object(target, "first")
            checkpoint = staging.checkpoint()
            staging.stage_object(target, "second")
            staging.rollback(checkpoint)

            self.assertEqual(pd.read_pickle(staging.source_path(target)), "first")

    def test_commit_failure_rolls_back_already_replaced_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            data.mkdir()
            first = data / "a.pkl"
            second = data / "b.pkl"
            pd.to_pickle("old-a", first)
            pd.to_pickle("old-b", second)
            staging = StagingArea(root / "staging", data)
            staging.stage_object(first, "new-a")
            staging.stage_object(second, "new-b")

            real_replace = storage_module.os.replace
            failed = False

            def fail_second_candidate(source: Path, destination: Path) -> None:
                nonlocal failed
                source_path = Path(source)
                if not failed and ".versions/2/" in str(source_path):
                    failed = True
                    raise OSError("simulated failure")
                real_replace(source, destination)

            with (
                patch.object(storage_module.os, "replace", fail_second_candidate),
                self.assertRaisesRegex(OSError, "simulated failure"),
            ):
                staging.commit()

            self.assertEqual(pd.read_pickle(first), "old-a")
            self.assertEqual(pd.read_pickle(second), "old-b")


if __name__ == "__main__":
    unittest.main()
