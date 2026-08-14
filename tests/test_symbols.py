from __future__ import annotations

import unittest

from data_factory.core.symbols import parse_symbol, unique_symbol_map


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


if __name__ == "__main__":
    unittest.main()
