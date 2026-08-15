from __future__ import annotations

import unittest

import pandas as pd

from data_factory.ingestion.models import UpdateError
from data_factory.ingestion.snapshots import validate_snapshot


class SnapshotValidationTests(unittest.TestCase):
    def test_frame_must_preserve_existing_keys(self) -> None:
        local = pd.DataFrame({"stkcode": ["A", "B", "C"], "name": ["a", "b", "c"]})
        incoming = pd.DataFrame({"stkcode": ["A", "D"], "name": ["a", "d"]})

        with self.assertRaisesRegex(UpdateError, "丢失了本地已有stkcode.*缺少 2 个"):
            validate_snapshot(local, incoming, "stk_info.pkl")

    def test_stale_delivery_says_so_instead_of_blaming_the_vendor(self) -> None:
        """输入是本地的子集时，最常见的原因是这批交付已经应用过。"""
        local = pd.DataFrame({"stkcode": ["A", "B"], "name": ["a", "b"]})
        incoming = local.iloc[:1].copy()

        with self.assertRaisesRegex(UpdateError, "已经应用过"):
            validate_snapshot(local, incoming, "stk_info.pkl")

    def test_series_stale_delivery_says_so(self) -> None:
        local = pd.Series([20260801, 20260802])
        incoming = pd.Series([20260801])

        with self.assertRaisesRegex(UpdateError, "已经应用过"):
            validate_snapshot(local, incoming, "trd_cal.pkl")

    def test_series_rejects_duplicate_values(self) -> None:
        local = pd.Series(["A", "B"])
        incoming = pd.Series(["A", "B", "B"])

        with self.assertRaisesRegex(UpdateError, "重复值"):
            validate_snapshot(local, incoming, "stkcode.pkl")

    def test_frame_requires_stable_column_order(self) -> None:
        local = pd.DataFrame({"stkcode": ["A"], "name": ["a"]})
        incoming = local[["name", "stkcode"]]

        with self.assertRaisesRegex(UpdateError, "字段变了"):
            validate_snapshot(local, incoming, "stk_info.pkl")


if __name__ == "__main__":
    unittest.main()
