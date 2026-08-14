from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from data_factory.processing import ConversionConfig, convert_dataset
from data_factory.quality import (
    CheckStatus,
    QualityIssue,
    QualityReport,
    run_checks,
)


class PublicApiTests(unittest.TestCase):
    def test_conversion_service_returns_structured_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input"
            source.mkdir()
            pd.DataFrame({"value": [1]}).to_pickle(source / "table.pkl")

            result = convert_dataset(
                ConversionConfig(
                    input_root=source,
                    output_root=root / "output",
                    part="regular",
                )
            )

            self.assertEqual(result.regular_counts["table"], 1)
            self.assertTrue((root / "output/table.parquet").exists())

    def test_dry_run_does_not_read_or_write_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input"
            minute = source / "market/bars/1m"
            minute.mkdir(parents=True)
            (source / "broken.pkl").write_bytes(b"not a pickle")
            (minute / "kline_day_20260102.pkl").write_bytes(b"not a pickle")
            output = root / "output"

            result = convert_dataset(
                ConversionConfig(
                    input_root=source,
                    output_root=output,
                    dry_run=True,
                )
            )

            self.assertTrue(result.dry_run)
            self.assertEqual(result.regular_counts["planned"], 1)
            self.assertEqual(result.minute_days, 1)
            self.assertFalse(output.exists())

    def test_quality_contract_has_derived_status(self) -> None:
        passing = QualityReport("passing")
        warning = QualityReport(
            "warning",
            issues=(QualityIssue("late", "数据延迟", CheckStatus.WARNING),),
        )
        self.assertTrue(passing.passed)
        self.assertEqual(warning.status, CheckStatus.WARNING)

    def test_run_checks_uses_common_interface(self) -> None:
        class ExampleCheck:
            name = "example"

            def run(self) -> QualityReport:
                return QualityReport(self.name, {"rows": 3})

        reports = run_checks([ExampleCheck()])
        self.assertEqual(reports[0].metrics["rows"], 3)


if __name__ == "__main__":
    unittest.main()
