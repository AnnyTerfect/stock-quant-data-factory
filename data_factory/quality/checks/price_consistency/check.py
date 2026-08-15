"""Minute-to-daily market price consistency check."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from data_factory.core.layout import FULL_ROOT
from data_factory.quality.checks.price_consistency.loaders import (
    load_daily_bundle,
    load_minute_day,
)
from data_factory.quality.checks.price_consistency.metrics import (
    aggregate_minute_prices,
    build_comparison,
    complete_rows,
    compute_stats,
    mismatch_table,
)
from data_factory.quality.models import (
    CheckOption,
    CheckSpec,
    CheckStatus,
    DataScope,
    QualityIssue,
    QualityReport,
)

CHECK_NAME = "price-consistency"


@dataclass(frozen=True, slots=True)
class PriceConsistencyCheck:
    """Compare minute bars aggregated to a day against the daily matrices."""

    trade_date: int
    input_root: Path = FULL_ROOT
    raw_tolerance: float = 1e-8
    show: int = 20

    @property
    def name(self) -> str:
        return CHECK_NAME

    @property
    def scope(self) -> DataScope:
        return DataScope.SOURCE

    def analyze(self) -> tuple[QualityReport, pd.DataFrame, pd.DataFrame]:
        """Return the report plus comparison and mismatch detail tables."""
        minute = load_minute_day(self.input_root, self.trade_date)
        daily = load_daily_bundle(self.input_root, self.trade_date)
        minute_daily = aggregate_minute_prices(
            minute, self.trade_date, str(self.input_root)
        )
        comparison, unmatched = build_comparison(minute_daily, daily)
        complete = complete_rows(comparison)
        stats = compute_stats(minute_daily, comparison, complete, unmatched)
        mismatches = mismatch_table(complete, self.raw_tolerance)

        issues: list[QualityIssue] = []
        if not stats["complete_codes"]:
            issues.append(
                QualityIssue("no_comparable_data", "没有字段完整、可用于比较的股票")
            )
        if stats["unmatched_codes"]:
            issues.append(
                QualityIssue(
                    "unmatched_symbols",
                    f"{stats['unmatched_codes']} 个分钟代码未匹配日线代码",
                    CheckStatus.WARNING,
                )
            )
        if not mismatches.empty:
            issues.append(
                QualityIssue(
                    "price_mismatch",
                    f"{len(mismatches)} 个价格点超过容差 {self.raw_tolerance:g}",
                    context={"rows": len(mismatches)},
                )
            )

        details: tuple[str, ...] = ()
        if not mismatches.empty and self.show > 0:
            details = (
                f"不匹配明细（前 {min(self.show, len(mismatches))} 条）:\n"
                + mismatches.head(self.show).to_string(),
            )
        report = QualityReport(
            self.name,
            {"trade_date": str(self.trade_date), **stats},
            tuple(issues),
            details,
        )
        return report, complete, mismatches

    def run(self) -> QualityReport:
        """Run through the generic :class:`QualityCheck` interface."""
        return self.analyze()[0]


SPEC = CheckSpec(
    name=CHECK_NAME,
    scope=DataScope.SOURCE,
    summary="分钟行情聚合到日频后与日线行情的一致性",
    factory=PriceConsistencyCheck,
    options=(
        CheckOption("trade_date", int, 20260722, "交易日 YYYYMMDD", flag="--date"),
        CheckOption("input_root", Path, FULL_ROOT, "源数据根目录", flag="--input"),
        CheckOption("raw_tolerance", float, 1e-8, "未复权价格的比较容差"),
        CheckOption("show", int, 20, "最多显示多少条不匹配记录"),
    ),
)
