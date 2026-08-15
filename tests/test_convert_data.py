from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from data_factory.processing import (
    ConversionConfig,
    RegularCounts,
    convert_minute_bars,
    convert_regular_pickles,
    normalize_daily_matrix,
    target_relative_path,
)


class ConvertDataTests(unittest.TestCase):
    def test_daily_matrix_filters_and_normalizes_axes(self) -> None:
        frame = pd.DataFrame(
            [[1.0, 2.0, 99.0]],
            index=pd.Index([20260102]),
            columns=["000001.SZ", "600000.SH", "not-a-stock"],
        )
        result, changed = normalize_daily_matrix(frame)
        self.assertTrue(changed)
        self.assertEqual(result.columns.tolist(), [1, 600000])
        self.assertEqual(result.columns.name, "stock_code")
        self.assertEqual(result.index.name, "datetime")
        self.assertEqual(result.index[0], pd.Timestamp("2026-01-02"))

    def test_daily_matrix_sorts_both_axes(self) -> None:
        frame = pd.DataFrame(
            [[1.0, 2.0], [3.0, 4.0]],
            index=pd.Index([20260105, 20260102]),
            columns=["600000.SH", "000001.SZ"],
        )
        result, changed = normalize_daily_matrix(frame)
        self.assertTrue(changed)
        self.assertEqual(result.columns.tolist(), [1, 600000])
        self.assertEqual(
            result.index.tolist(),
            [pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-05")],
        )
        # Sorting has to carry the values along, not just relabel the axes.
        self.assertEqual(result.loc[pd.Timestamp("2026-01-02"), 1], 4.0)
        self.assertEqual(result.loc[pd.Timestamp("2026-01-05"), 600000], 1.0)

    def test_daily_matrix_left_alone_without_symbol_columns(self) -> None:
        frame = pd.DataFrame([[1.0]], index=pd.Index([20260102]), columns=["value"])
        result, changed = normalize_daily_matrix(frame)
        self.assertFalse(changed)
        self.assertIs(result, frame)

    def test_requested_path_renames(self) -> None:
        self.assertEqual(
            target_relative_path(Path("barra/BETA.pkl")).as_posix(),
            "barra/beta.parquet",
        )
        self.assertEqual(
            target_relative_path(Path("full/barra/BP.pkl")).as_posix(),
            "full/barra/book_to_price.parquet",
        )
        self.assertEqual(
            target_relative_path(Path("market/adjustment/adjfactor.pkl")).as_posix(),
            "market/adjustment/adj_factor.parquet",
        )
        self.assertEqual(
            target_relative_path(Path("full/universe/a.pkl")).as_posix(),
            "full/universe/a.parquet",
        )

    def test_minute_pivot_shift_and_adjustment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_root = root / "data"
            minute_root = input_root / "full/market/bars/1m"
            factor_root = input_root / "full/market/adjustment"
            minute_root.mkdir(parents=True)
            factor_root.mkdir(parents=True)

            factors = pd.DataFrame(
                [[2.0, 3.0], [2.5, 3.5]],
                index=[20260102, 20260105],
                columns=["000001.SZ", "600000.SH"],
            )
            factors.to_pickle(factor_root / "adjfactor.pkl")
            minute = pd.DataFrame(
                {
                    "code": [1, 600000, 1],
                    "date": [20260102] * 3,
                    "time": [959, 959, 1459],
                    "open": [10.0, 20.0, 11.0],
                    "high": [10.5, 20.5, 11.5],
                    "low": [9.5, 19.5, 10.5],
                    "close": [10.2, 20.2, 11.2],
                    "volume": [100, 200, 300],
                    "amount": [1000.0, 4000.0, 3300.0],
                }
            )
            minute.to_pickle(minute_root / "kline_day_20260102.pkl")
            later = minute.iloc[:2].copy()
            later["date"] = 20260105
            later.to_pickle(minute_root / "kline_day_20260105.pkl")

            output_root = root / "data-out"
            config = ConversionConfig(input_root=input_root, output_root=output_root)
            self.assertEqual(convert_minute_bars(config), 2)
            bar_root = output_root / "full/market/bars/1m"
            opened = pd.read_parquet(bar_root / "open.parquet")
            volume = pd.read_parquet(bar_root / "volume.parquet")
            self.assertEqual(opened.columns.tolist(), [1, 600000])
            self.assertEqual(opened.columns.name, "stock_code")
            self.assertEqual(opened.index.name, "datetime")
            self.assertIn(pd.Timestamp("2026-01-02 10:00"), opened.index)
            self.assertIn(pd.Timestamp("2026-01-02 15:00"), opened.index)
            self.assertTrue(opened.index.is_monotonic_increasing)
            self.assertIn(pd.Timestamp("2026-01-05 10:00"), opened.index)
            self.assertEqual(opened.loc["2026-01-02 10:00", 1], 20.0)
            self.assertEqual(opened.loc["2026-01-02 10:00", 600000], 60.0)
            self.assertEqual(opened.loc["2026-01-05 10:00", 1], 25.0)
            self.assertEqual(volume.loc["2026-01-02 10:00", 1], 100.0)

    def test_regular_conversion_skips_current_layout_minute_bars(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_root = root / "data"
            minute_root = input_root / "market/bars/1m"
            minute_root.mkdir(parents=True)
            pd.DataFrame({"value": [1]}).to_pickle(
                minute_root / "kline_day_20260102.pkl"
            )

            output_root = root / "data-out"
            counts = convert_regular_pickles(
                ConversionConfig(input_root=input_root, output_root=output_root)
            )
            self.assertEqual(counts, RegularCounts())
            self.assertFalse((output_root / "market/bars/1m").exists())

    def test_plain_table_gets_sorted_rows_and_declared_column_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_root = root / "data"
            reference_root = input_root / "reference"
            reference_root.mkdir(parents=True)
            pd.DataFrame(
                {"stkcode": ["b", "a"], "listdate": [20260105, 20260102]},
                index=pd.Index([1, 0]),
            ).to_pickle(reference_root / "stk_info.pkl")

            output_root = root / "data-out"
            convert_regular_pickles(
                ConversionConfig(input_root=input_root, output_root=output_root)
            )
            table = pd.read_parquet(output_root / "reference/stk_info.parquet")
            self.assertEqual(table.index.tolist(), [0, 1])
            self.assertEqual(table["stkcode"].tolist(), ["a", "b"])
            self.assertEqual(table.columns.tolist(), ["stkcode", "listdate"])

    def test_regular_conversion_accepts_every_pickle_suffix(self) -> None:
        """Conversion has to recognize exactly what ingestion is willing to index.

        ``build_catalog`` accepts ``.pkl`` and ``.pickle`` case-insensitively, so
        a file ingested under any of those spellings must convert to parquet
        rather than fall through to the verbatim copy.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_root = root / "data"
            reference_root = input_root / "reference"
            reference_root.mkdir(parents=True)
            for name in ("lower.pkl", "other.pickle", "upper.PKL"):
                pd.DataFrame({"value": [1]}).to_pickle(reference_root / name)

            output_root = root / "data-out"
            counts = convert_regular_pickles(
                ConversionConfig(input_root=input_root, output_root=output_root)
            )
            self.assertEqual(counts, RegularCounts(table=3))
            for stem in ("lower", "other", "upper"):
                self.assertTrue((output_root / f"reference/{stem}.parquet").exists())


if __name__ == "__main__":
    unittest.main()
