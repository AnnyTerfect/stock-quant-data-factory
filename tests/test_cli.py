from __future__ import annotations

import unittest
from pathlib import Path

from data_factory.cli.main import build_parser
from data_factory.cli.render import render_report
from data_factory.core.layout import FULL_ROOT, INCREMENTAL_ROOT, delivery_dir
from data_factory.quality import registry
from data_factory.quality.models import CheckStatus, QualityIssue, QualityReport


class CliTests(unittest.TestCase):
    def test_convert_subcommand(self) -> None:
        args = build_parser().parse_args(
            ["convert", "--part", "regular", "--dry-run", "--workers", "3"]
        )
        self.assertEqual(args.command, "convert")
        self.assertEqual(args.part, "regular")
        self.assertTrue(args.dry_run)
        self.assertEqual(args.workers, 3)

    def test_update_subcommand(self) -> None:
        args = build_parser().parse_args(
            ["update", "--delivery", "2026-08-08", "--trusted-pickle", "--dry-run"]
        )
        self.assertEqual(args.command, "update")
        self.assertEqual(args.delivery, Path("2026-08-08"))
        self.assertEqual(args.data, FULL_ROOT)
        self.assertTrue(args.trusted_pickle)
        self.assertTrue(args.dry_run)

    def test_update_requires_a_delivery(self) -> None:
        """默认更新哪批交付是猜不得的，只有数据目录有约定俗成的位置。"""
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["update", "--trusted-pickle"])

    def test_bare_delivery_name_resolves_under_the_incremental_root(self) -> None:
        self.assertEqual(delivery_dir("2026-08-08"), INCREMENTAL_ROOT / "2026-08-08")
        self.assertEqual(
            delivery_dir(Path("other/2026-08-08")), Path("other/2026-08-08")
        )

    def test_every_command_accepts_a_log_directory(self) -> None:
        parser = build_parser()
        update = parser.parse_args(["update", "--delivery", "d", "--log-dir", "a"])
        convert = parser.parse_args(["convert", "--log-dir", "a"])
        check = parser.parse_args(["check", "price-consistency", "--log-dir", "b"])
        self.assertEqual(update.log_dir, Path("a"))
        self.assertEqual(convert.log_dir, Path("a"))
        self.assertEqual(check.log_dir, Path("b"))

    def test_check_subcommands_come_from_the_registry(self) -> None:
        parser = build_parser()
        for name in registry.names():
            with self.subTest(check=name):
                args = parser.parse_args(["check", name])
                self.assertEqual(args.command, "check")
                self.assertEqual(args.spec.name, name)

    def test_check_options_are_declared_by_the_spec(self) -> None:
        args = build_parser().parse_args(
            ["check", "price-consistency", "--date", "20260102", "--show", "5"]
        )
        self.assertEqual(args.trade_date, 20260102)
        self.assertEqual(args.show, 5)

    def test_spec_builds_a_check_from_its_defaults(self) -> None:
        spec = registry.get("price-consistency")
        check = spec.build({"trade_date": 20260102})
        self.assertEqual(check.trade_date, 20260102)
        self.assertEqual(check.show, spec.defaults()["show"])

    def test_spec_rejects_unknown_options(self) -> None:
        with self.assertRaises(KeyError):
            registry.get("price-consistency").build({"nope": 1})

    def test_unknown_check_names_list_the_alternatives(self) -> None:
        with self.assertRaises(KeyError) as caught:
            registry.get("nope")
        self.assertIn("price-consistency", str(caught.exception))


class RenderTests(unittest.TestCase):
    def test_renders_any_report_without_check_specific_knowledge(self) -> None:
        report = QualityReport(
            "example",
            {"trade_date": "20260102", "rows": 1234567, "error": 0.000123456789},
            (QualityIssue("late", "数据延迟", CheckStatus.WARNING),),
            ("明细:\n  a  b",),
        )
        text = render_report(report)
        self.assertIn("[example] 检查结果: warning", text)
        self.assertIn("20260102", text)
        self.assertIn("1,234,567", text)
        self.assertIn("0.000123457", text)
        self.assertIn("[warning] late: 数据延迟", text)
        self.assertIn("明细:", text)


if __name__ == "__main__":
    unittest.main()
