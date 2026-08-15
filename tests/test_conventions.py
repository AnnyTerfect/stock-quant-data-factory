from __future__ import annotations

import unittest

import pandas as pd

from data_factory.core.conventions import (
    DateAxisError,
    ensure_sorted_dates,
    ensure_unique_dates,
    format_dates,
    is_integer_date_axis,
    parse_symbol,
    to_datetime_index,
    to_integer_dates,
    unique_symbol_map,
)


class SymbolTests(unittest.TestCase):
    def test_parses_market_suffixed_symbols(self) -> None:
        self.assertEqual(parse_symbol("000001.SZ"), 1)
        self.assertEqual(parse_symbol("600000.sh"), 600000)

    def test_rejects_everything_else(self) -> None:
        for value in ("000001", "000001.SSE", "not-a-stock", 600000, ""):
            with self.subTest(value=value):
                self.assertIsNone(parse_symbol(value))

    def test_map_keeps_first_appearance_order(self) -> None:
        symbols = unique_symbol_map(["600000.SH", "000001.SZ", "bad"])
        self.assertEqual(list(symbols), [600000, 1])
        self.assertEqual(symbols[1], "000001.SZ")

    def test_map_rejects_codes_claimed_twice(self) -> None:
        with self.assertRaises(ValueError):
            unique_symbol_map(["000001.SZ", "000001.SH"])


class TradingDateTests(unittest.TestCase):
    def test_recognizes_an_eight_digit_axis(self) -> None:
        self.assertTrue(is_integer_date_axis([20260102, 20260105]))
        self.assertTrue(is_integer_date_axis(["20260102"]))

    def test_rejects_axes_that_are_not_eight_digit_days(self) -> None:
        for values in ([2026, 1], ["2026-01-02"], [20260102, "x"], [202601021]):
            with self.subTest(values=values):
                self.assertFalse(is_integer_date_axis(values))

    def test_empty_axis_is_not_a_date_axis(self) -> None:
        """Otherwise an empty table of any shape would be rewritten as a matrix."""
        self.assertFalse(is_integer_date_axis([]))

    def test_parses_integers_and_passes_datetimes_through(self) -> None:
        parsed = to_datetime_index([20260102, 20260105])
        self.assertEqual(
            list(parsed), [pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-05")]
        )

        # Already-parsed axes go through untouched: stringifying "2026-01-02"
        # first would make it stop matching DATE_FORMAT.
        already = pd.DatetimeIndex(["2026-01-02"])
        self.assertEqual(list(to_datetime_index(already)), list(already))

    def test_parse_reports_the_offending_values(self) -> None:
        with self.assertRaisesRegex(DateAxisError, r"20261301"):
            to_datetime_index([20260102, 20261301])

    def test_round_trips_back_to_upstream_integers(self) -> None:
        dates = to_datetime_index([20260102, 20260105])
        self.assertEqual(list(to_integer_dates(dates)), [20260102, 20260105])

    def test_uniqueness_and_order_are_separate_rules(self) -> None:
        repeated = to_datetime_index([20260102, 20260102])
        with self.assertRaisesRegex(DateAxisError, "重复"):
            ensure_unique_dates(repeated)
        # Repetition alone must not read as disorder, nor the reverse.
        ensure_sorted_dates(repeated)

        descending = to_datetime_index([20260105, 20260102])
        with self.assertRaisesRegex(DateAxisError, "升序"):
            ensure_sorted_dates(descending)
        ensure_unique_dates(descending)

    def test_formats_a_bounded_number_of_examples(self) -> None:
        dates = to_datetime_index([20260102, 20260105, 20260106])
        self.assertEqual(format_dates(dates, limit=2), ["20260102", "20260105"])


if __name__ == "__main__":
    unittest.main()
