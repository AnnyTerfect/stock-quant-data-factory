from __future__ import annotations

import unittest

from data_factory.cli.main import build_parser


class CliTests(unittest.TestCase):
    def test_convert_subcommand(self) -> None:
        args = build_parser().parse_args(["convert", "--part", "regular", "--dry-run"])
        self.assertEqual(args.command, "convert")
        self.assertEqual(args.part, "regular")
        self.assertTrue(args.dry_run)

    def test_check_subcommand(self) -> None:
        args = build_parser().parse_args(["check", "--date", "20260102"])
        self.assertEqual(args.command, "check")
        self.assertEqual(args.date, 20260102)


if __name__ == "__main__":
    unittest.main()
