from __future__ import annotations

import unittest

import pandas as pd

from data_factory.quality.checks.price_consistency import (
    DailyBundle,
    aggregate_minute_prices,
    build_comparison,
    complete_rows,
    compute_stats,
    mismatch_table,
)

TRADE_DATE = 20260102
SYMBOLS = ["000001.SZ", "600000.SH"]


def minute_frame() -> pd.DataFrame:
    """Two stocks, two bars each; 000001 peaks in the second bar."""
    return pd.DataFrame(
        {
            "code": [1, 1, 600000, 600000],
            "date": [TRADE_DATE] * 4,
            "time": [930, 1459, 930, 1459],
            "open": [10.0, 11.0, 20.0, 21.0],
            "high": [10.5, 12.0, 20.5, 21.5],
            "low": [9.5, 10.8, 19.5, 20.8],
            "close": [10.2, 11.5, 20.2, 21.2],
            "volume": [10_000, 20_000, 30_000, 40_000],
            "amount": [1_000_000.0, 2_000_000.0, 3_000_000.0, 4_000_000.0],
        }
    )


def daily_bundle(
    factor: float = 2.0, close_override: float | None = None
) -> DailyBundle:
    """Daily matrices that agree exactly with :func:`minute_frame`."""
    index = pd.Index(SYMBOLS)
    adjust_factor = pd.Series([factor, factor], index=index)
    raw = {"open": [10.0, 20.0], "high": [12.0, 21.5], "low": [9.5, 19.5]}
    raw["close"] = [close_override if close_override is not None else 11.5, 21.2]
    return DailyBundle(
        trade_date=TRADE_DATE,
        adjust_factor=adjust_factor,
        adjusted_prices={
            field: pd.Series(values, index=index) * factor
            for field, values in raw.items()
        },
        volume=pd.Series([3.0, 7.0], index=index),
        amount=pd.Series([3.0, 7.0], index=index),
        adjusted_vwap=pd.Series([1_000_000.0, 1_000_000.0], index=index) * factor,
    )


class AggregateMinutePricesTests(unittest.TestCase):
    def test_collapses_bars_into_a_daily_bar(self) -> None:
        result = aggregate_minute_prices(minute_frame(), TRADE_DATE)
        first = result.loc[1]
        self.assertEqual(first["open"], 10.0)
        self.assertEqual(first["close"], 11.5)
        self.assertEqual(first["high"], 12.0)
        self.assertEqual(first["low"], 9.5)
        self.assertEqual(first["volume"], 30_000)
        self.assertEqual(first["minute_rows"], 2)

    def test_records_when_the_extremes_happened(self) -> None:
        result = aggregate_minute_prices(minute_frame(), TRADE_DATE)
        self.assertEqual(result.loc[1, "high_time"], 1459)
        self.assertEqual(result.loc[1, "low_time"], 930)

    def test_rejects_missing_fields(self) -> None:
        with self.assertRaises(ValueError):
            aggregate_minute_prices(minute_frame().drop(columns=["amount"]), TRADE_DATE)

    def test_rejects_a_day_with_no_rows(self) -> None:
        with self.assertRaises(ValueError):
            aggregate_minute_prices(minute_frame(), 20260103)


class ComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.minute_daily = aggregate_minute_prices(minute_frame(), TRADE_DATE)

    def test_matches_minute_codes_to_daily_symbols(self) -> None:
        comparison, unmatched = build_comparison(self.minute_daily, daily_bundle())
        self.assertEqual(unmatched, [])
        self.assertEqual(sorted(comparison.index), SYMBOLS)
        self.assertAlmostEqual(comparison.loc["000001.SZ", "minute_adj_close"], 23.0)
        self.assertAlmostEqual(comparison.loc["000001.SZ", "daily_raw_close"], 11.5)

    def test_reports_minute_codes_absent_from_the_daily_universe(self) -> None:
        daily = daily_bundle()
        trimmed = DailyBundle(
            trade_date=daily.trade_date,
            adjust_factor=daily.adjust_factor.drop("600000.SH"),
            adjusted_prices={
                field: values.drop("600000.SH")
                for field, values in daily.adjusted_prices.items()
            },
            volume=daily.volume,
            amount=daily.amount,
            adjusted_vwap=daily.adjusted_vwap,
        )
        comparison, unmatched = build_comparison(self.minute_daily, trimmed)
        self.assertEqual(unmatched, [600000])
        self.assertEqual(list(comparison.index), ["000001.SZ"])

    def test_agreeing_sources_produce_no_mismatches(self) -> None:
        comparison, _ = build_comparison(self.minute_daily, daily_bundle())
        complete = complete_rows(comparison)
        self.assertEqual(len(complete), 2)
        self.assertTrue(mismatch_table(complete).empty)

    def test_disagreeing_close_price_is_reported(self) -> None:
        comparison, _ = build_comparison(
            self.minute_daily, daily_bundle(close_override=11.6)
        )
        mismatches = mismatch_table(complete_rows(comparison))
        self.assertEqual(len(mismatches), 1)
        row = mismatches.iloc[0]
        self.assertEqual(row["field"], "close")
        self.assertEqual(row["minute_time"], "14:59")
        self.assertAlmostEqual(row["adjusted_abs_error"], 0.2)

    def test_tolerance_suppresses_small_differences(self) -> None:
        comparison, _ = build_comparison(
            self.minute_daily, daily_bundle(close_override=11.6)
        )
        complete = complete_rows(comparison)
        self.assertTrue(mismatch_table(complete, raw_tolerance=1.0).empty)

    def test_stats_summarize_the_agreement(self) -> None:
        comparison, unmatched = build_comparison(self.minute_daily, daily_bundle())
        complete = complete_rows(comparison)
        stats = compute_stats(self.minute_daily, comparison, complete, unmatched)
        self.assertEqual(stats["minute_rows"], 4)
        self.assertEqual(stats["minute_codes"], 2)
        self.assertEqual(stats["matched_codes"], 2)
        self.assertEqual(stats["complete_codes"], 2)
        self.assertEqual(stats["price_points"], 8)
        self.assertEqual(stats["raw_exact_points"], 8)
        self.assertAlmostEqual(stats["multiply_median_error"], 0.0)
        self.assertEqual(stats["volume_match_points"], 2)
        self.assertEqual(stats["amount_match_points"], 2)


if __name__ == "__main__":
    unittest.main()
