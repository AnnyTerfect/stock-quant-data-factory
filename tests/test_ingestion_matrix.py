from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from data_factory.ingestion.matrix import (
    compare_overlap,
    ensure_covers_local_stocks,
    has_date_axis,
    merge,
)
from data_factory.ingestion.models import Tolerance, UpdateError


def _frame(values: object, dates: list[int], stocks: list[str], dtype: object = None):
    return pd.DataFrame(values, index=pd.Index(dates), columns=stocks, dtype=dtype)


class CompareOverlapTests(unittest.TestCase):
    def test_nullable_strings_compare_without_ambiguous_na(self) -> None:
        local = pd.DataFrame(
            {"A": pd.array(["open", pd.NA], dtype="string")},
            index=[20260801, 20260802],
        )
        incoming = local.copy()

        report = compare_overlap(local, incoming, "status.pkl", Tolerance())

        self.assertEqual(report.mismatches, 0)

    def test_reports_max_relative_deviation(self) -> None:
        """只看差异条数分不清浮点噪声和真的算错了，偏差幅度才是可分诊的信号。"""
        local = _frame([[1.0, 100.0]], [20260801], ["A", "B"])
        incoming = _frame([[1.0000001, 110.0]], [20260801], ["A", "B"])

        report = compare_overlap(local, incoming, "f.pkl", Tolerance(1e-9, 0.0))

        self.assertEqual(report.mismatches, 2)
        self.assertAlmostEqual(report.max_deviation, 10.0 / 110.0, places=6)
        self.assertIn("最大相对偏差", report.mismatch_message("f.pkl"))


class EnsureCoversLocalStocksTests(unittest.TestCase):
    def test_rejects_shrinking_stock_universe(self) -> None:
        """全量覆盖没有兜底，输入少一批股票就等于把它们的历史直接删掉。"""
        local = _frame(1.0, [20260801], ["A", "B", "C"])
        incoming = _frame(1.0, [20260801], ["A", "B"])

        with self.assertRaisesRegex(UpdateError, "缺少 1 只本地已有股票"):
            ensure_covers_local_stocks(local, incoming, "Barra/SIZE.pkl")

    def test_accepts_growing_stock_universe(self) -> None:
        local = _frame(1.0, [20260801], ["A"])
        incoming = _frame(1.0, [20260801], ["A", "B"])

        ensure_covers_local_stocks(local, incoming, "Barra/SIZE.pkl")


class HasDateAxisTests(unittest.TestCase):
    def test_accepts_yyyymmdd_integers(self) -> None:
        self.assertTrue(has_date_axis(pd.Index([20050104, 20260803])))

    def test_rejects_row_numbers(self) -> None:
        """ind_code_CI.pkl 的行索引就是 0..570，按日期合并会把它改坏。"""
        self.assertFalse(has_date_axis(pd.RangeIndex(571)))

    def test_rejects_empty_and_non_integer(self) -> None:
        self.assertFalse(has_date_axis(pd.Index([], dtype="int64")))
        self.assertFalse(has_date_axis(pd.Index(["000001.SZ"])))


class MergeTests(unittest.TestCase):
    def test_keeps_local_only_stocks_on_new_dates(self) -> None:
        local = _frame([[1.0, 2.0]], [20260801], ["A", "B"])
        incoming = _frame([[3.0]], [20260802], ["A"])

        merged = merge(local, incoming, "f.pkl")

        self.assertEqual(merged.loc[20260801, "B"], 2.0)
        self.assertEqual(merged.loc[20260802, "A"], 3.0)
        self.assertTrue(pd.isna(merged.loc[20260802, "B"]))

    def test_incoming_overwrites_overlap_regardless_of_axis_order(self) -> None:
        local = _frame(
            [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], [20260801, 20260802], list("ABC")
        )
        incoming = _frame(
            [[60.0, 40.0], [99.0, 77.0]], [20260803, 20260802], ["C", "A"]
        )

        merged = merge(local, incoming, "f.pkl")

        self.assertEqual(merged.loc[20260802, "A"], 77.0)
        self.assertEqual(merged.loc[20260802, "C"], 99.0)
        self.assertEqual(merged.loc[20260803, "C"], 60.0)
        self.assertEqual(list(merged.index), [20260801, 20260802, 20260803])
        self.assertEqual(list(merged.columns), ["A", "B", "C"])

    def test_widening_dtype_does_not_crash(self) -> None:
        """pandas 3.0 的 .loc 赋值不再隐式放宽 dtype，供应商提一次精度就会抛错。"""
        local = _frame(1.0, [20260801], ["A"], dtype=np.float16)
        incoming = _frame(1.2345678, [20260802], ["A"], dtype=np.float32)

        merged = merge(local, incoming, "f.pkl")

        self.assertEqual(merged.dtypes.iloc[0], np.float32)
        self.assertAlmostEqual(merged.loc[20260802, "A"], 1.2345678, places=6)

    def test_widening_dtype_does_not_crash_on_mixed_dtype_frames(self) -> None:
        local = pd.DataFrame(
            {
                "A": np.array([1.0], dtype=np.float16),
                "B": np.array([2], dtype=np.int64),
            },
            index=pd.Index([20260801]),
        )
        incoming = pd.DataFrame(
            {
                "A": np.array([9.5], dtype=np.float32),
                "B": np.array([3], dtype=np.int64),
            },
            index=pd.Index([20260801]),
        )

        merged = merge(local, incoming, "f.pkl")

        self.assertAlmostEqual(merged.loc[20260801, "A"], 9.5, places=6)
        self.assertEqual(merged.loc[20260801, "B"], 3)

    def test_preserves_narrow_dtype_when_nothing_widens(self) -> None:
        local = _frame(1.0, [20260801, 20260802], ["A"], dtype=np.float16)
        incoming = _frame(2.0, [20260803], ["A"], dtype=np.float16)

        merged = merge(local, incoming, "f.pkl")

        self.assertEqual(merged.dtypes.iloc[0], np.float16)

    def test_integer_matrix_promotes_only_when_gaps_appear(self) -> None:
        local = _frame(1, [20260801], ["A"], dtype=np.int64)

        no_gap = merge(local, _frame(2, [20260802], ["A"], dtype=np.int64), "f.pkl")
        self.assertEqual(no_gap.dtypes.iloc[0], np.int64)

        gapped = merge(local, _frame(2, [20260802], ["B"], dtype=np.int64), "f.pkl")
        self.assertTrue(pd.isna(gapped.loc[20260802, "A"]))

    def test_numpy_and_pandas_paths_agree(self) -> None:
        """同构矩阵走 numpy 快路径，结果必须和逐列赋值的通用路径一致。"""
        dates = [20260801, 20260802, 20260803]
        local = _frame(np.arange(9, dtype=np.float64).reshape(3, 3), dates, list("ABC"))
        incoming = _frame(
            np.arange(4, dtype=np.float64).reshape(2, 2) * 10,
            [20260803, 20260804],
            ["B", "D"],
        )

        fast = merge(local, incoming, "f.pkl")

        reference = local.reindex(index=[*dates, 20260804], columns=list("ABCD"))
        reference.loc[incoming.index, incoming.columns] = incoming.to_numpy()
        pd.testing.assert_frame_equal(fast, reference, check_names=False)


if __name__ == "__main__":
    unittest.main()
