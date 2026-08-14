"""Command-line entry point for minute/daily consistency checks."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from pathlib import Path

from data_factory.quality import PriceConsistencyCheck


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Register quality-check arguments on a command parser."""
    parser.add_argument("--date", type=int, default=20260722)
    parser.add_argument("--minute-dir", type=Path, default=Path("1min_kline"))
    parser.add_argument("--daily-dir", type=Path, default=Path("daily_kline"))
    parser.add_argument("--raw-tolerance", type=float, default=1e-8)
    parser.add_argument("--show", type=int, default=20, help="最多显示多少条不匹配记录")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    return parser


def run(args: argparse.Namespace) -> None:
    """Execute a parsed quality-check command."""
    check = PriceConsistencyCheck(
        args.date, args.minute_dir, args.daily_dir, args.raw_tolerance
    )
    report, _, mismatches = check.analyze()
    metrics = report.metrics
    print(f"日期: {args.date}，检查结果: {report.status.value}")
    print(
        f"分钟记录 {metrics['minute_rows']:,} 行，股票 {metrics['minute_codes']:,} 只；"
        f"成功匹配 {metrics['matched_codes']:,} 只，完整可比 {metrics['complete_codes']:,} 只。"
    )
    print(
        "复权乘法误差: "
        f"中位数={metrics['multiply_median_error']:.6g}, "
        f"P99={metrics['multiply_p99_error']:.6g}"
    )
    if report.issues:
        for issue in report.issues:
            print(f"[{issue.status.value}] {issue.code}: {issue.message}")
    if not mismatches.empty:
        print(mismatches.head(args.show).to_string())


def main(argv: Iterable[str] | None = None) -> None:
    run(build_parser().parse_args(argv))
