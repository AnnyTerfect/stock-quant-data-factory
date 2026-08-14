"""Minute-to-daily market price consistency check."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from data_factory.quality.models import CheckStatus, QualityIssue, QualityReport

PRICE_FIELDS = ("open", "high", "low", "close")
VOLUME_SCALE = 10_000
AMOUNT_SCALE = 1_000_000


def _safe_median(values: np.ndarray | pd.Series) -> float:
    return float(np.nanmedian(values)) if len(values) else float("nan")


def _safe_quantile(values: np.ndarray, quantile: float) -> float:
    return float(np.nanquantile(values, quantile)) if len(values) else float("nan")


def _safe_max(values: pd.Series) -> float:
    return float(values.max()) if len(values) else float("nan")


def aggregate_minute_prices(path: Path, trade_date: int) -> pd.DataFrame:
    minute = pd.read_pickle(path)
    if not isinstance(minute, pd.DataFrame):
        raise TypeError(f"{path} 不是 DataFrame")
    required = {"code", "date", "time", "volume", "amount", *PRICE_FIELDS}
    missing = required.difference(minute.columns)
    if missing:
        raise ValueError(f"{path} 缺少字段: {sorted(missing)}")
    minute = minute.loc[minute["date"].eq(trade_date)].sort_values(
        ["code", "time"], kind="stable"
    )
    if minute.empty:
        raise ValueError(f"{path} 中没有 {trade_date} 的数据")
    grouped = minute.groupby("code", sort=False)
    result = grouped.agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        amount=("amount", "sum"),
        open_time=("time", "first"),
        close_time=("time", "last"),
        minute_rows=("time", "size"),
    )
    result["high_time"] = (
        minute.loc[grouped["high"].idxmax(), ["code", "time"]]
        .set_index("code")["time"]
        .reindex(result.index)
    )
    result["low_time"] = (
        minute.loc[grouped["low"].idxmin(), ["code", "time"]]
        .set_index("code")["time"]
        .reindex(result.index)
    )
    return result


def build_symbol_lookup(columns: pd.Index) -> dict[int, str]:
    candidates: dict[int, list[str]] = {}
    for column in columns.astype(str):
        numeric_part = column.split(".", maxsplit=1)[0]
        if numeric_part.isdigit():
            candidates.setdefault(int(numeric_part), []).append(column)
    ambiguous = {code: names for code, names in candidates.items() if len(names) > 1}
    if ambiguous:
        raise ValueError(
            f"日线代码去掉市场后缀后不唯一，例如: {dict(list(ambiguous.items())[:5])}"
        )
    return {code: names[0] for code, names in candidates.items()}


def load_daily_row(path: Path, trade_date: int) -> pd.Series:
    frame = pd.read_pickle(path)
    if not isinstance(frame, (pd.DataFrame, pd.Series)):
        raise TypeError(f"{path} 不是 DataFrame 或 Series")
    if trade_date not in frame.index:
        raise ValueError(f"{path} 中没有 {trade_date}")
    return frame.loc[trade_date]


def compare_prices(
    trade_date: int, minute_dir: Path, daily_dir: Path
) -> tuple[pd.DataFrame, dict[str, float | int]]:
    minute_daily = aggregate_minute_prices(
        minute_dir / f"kline_day_{trade_date}.pkl", trade_date
    )
    factor = load_daily_row(daily_dir / "adjfactor.pkl", trade_date)
    symbol_lookup = build_symbol_lookup(factor.index)
    minute_daily["symbol"] = [
        symbol_lookup.get(int(code)) for code in minute_daily.index
    ]
    unmatched_codes = minute_daily.index[minute_daily["symbol"].isna()].tolist()
    comparison = minute_daily.dropna(subset=["symbol"]).set_index("symbol")
    comparison["adjfactor"] = factor.reindex(comparison.index)

    for field in PRICE_FIELDS:
        adjusted = load_daily_row(daily_dir / f"adj_{field}.pkl", trade_date)
        comparison[f"daily_adj_{field}"] = adjusted.reindex(comparison.index)
        comparison[f"minute_adj_{field}"] = comparison[field] * comparison["adjfactor"]
        comparison[f"daily_raw_{field}"] = (
            comparison[f"daily_adj_{field}"] / comparison["adjfactor"]
        )
        comparison[f"raw_diff_{field}"] = (
            comparison[field] - comparison[f"daily_raw_{field}"]
        )

    comparison["daily_volume"] = load_daily_row(
        daily_dir / "volume.pkl", trade_date
    ).reindex(comparison.index)
    comparison["daily_amount"] = load_daily_row(
        daily_dir / "amount.pkl", trade_date
    ).reindex(comparison.index)
    comparison["daily_adj_vwap"] = load_daily_row(
        daily_dir / "adj_vwap.pkl", trade_date
    ).reindex(comparison.index)
    comparison["minute_daily_unit_volume"] = comparison["volume"] / VOLUME_SCALE
    comparison["minute_daily_unit_amount"] = comparison["amount"] / AMOUNT_SCALE
    comparison["minute_vwap"] = comparison["amount"] / comparison["volume"]
    comparison["minute_adj_vwap"] = comparison["minute_vwap"] * comparison["adjfactor"]
    comparison["daily_raw_vwap"] = (
        comparison["daily_adj_vwap"] / comparison["adjfactor"]
    )

    required = [
        "adjfactor",
        "daily_volume",
        "daily_amount",
        "daily_adj_vwap",
        *[f"daily_adj_{f}" for f in PRICE_FIELDS],
    ]
    complete = comparison.dropna(subset=required).copy()
    multiply_errors = np.concatenate(
        [
            (complete[f] * complete["adjfactor"] - complete[f"daily_adj_{f}"])
            .abs()
            .to_numpy()
            for f in PRICE_FIELDS
        ]
    )
    divide_errors = np.concatenate(
        [
            (complete[f] / complete["adjfactor"] - complete[f"daily_adj_{f}"])
            .abs()
            .to_numpy()
            for f in PRICE_FIELDS
        ]
    )
    raw_errors = np.concatenate(
        [complete[f"raw_diff_{f}"].abs().to_numpy() for f in PRICE_FIELDS]
    )
    volume_errors = (
        complete["minute_daily_unit_volume"] - complete["daily_volume"]
    ).abs()
    amount_errors = (
        complete["minute_daily_unit_amount"] - complete["daily_amount"]
    ).abs()
    raw_vwap_errors = (complete["minute_vwap"] - complete["daily_raw_vwap"]).abs()
    stats: dict[str, float | int] = {
        "minute_rows": int(minute_daily["minute_rows"].sum()),
        "minute_codes": len(minute_daily),
        "matched_codes": len(comparison),
        "unmatched_codes": len(unmatched_codes),
        "complete_codes": len(complete),
        "price_points": len(raw_errors),
        "raw_exact_points": int(np.isclose(raw_errors, 0, atol=1e-10).sum()),
        "multiply_median_error": _safe_median(multiply_errors),
        "multiply_p99_error": _safe_quantile(multiply_errors, 0.99),
        "divide_median_error": _safe_median(divide_errors),
        "divide_p99_error": _safe_quantile(divide_errors, 0.99),
        "volume_match_points": int(volume_errors.le(1e-8).sum()),
        "volume_max_error": _safe_max(volume_errors),
        "amount_match_points": int(amount_errors.le(5.1e-7).sum()),
        "amount_max_error": _safe_max(amount_errors),
        "vwap_match_points": int(raw_vwap_errors.le(5.1e-5).sum()),
        "vwap_median_error": _safe_median(raw_vwap_errors),
        "vwap_max_error": _safe_max(raw_vwap_errors),
    }
    return complete, stats


def mismatch_table(
    comparison: pd.DataFrame, raw_tolerance: float = 1e-8
) -> pd.DataFrame:
    parts = []
    for field in PRICE_FIELDS:
        part = comparison[
            [field, f"daily_raw_{field}", f"daily_adj_{field}", "adjfactor"]
        ].copy()
        part.columns = ["minute_raw", "daily_raw_implied", "daily_adj", "adjfactor"]
        part["field"] = field
        raw_time = comparison[f"{field}_time"].astype("Int64").astype(str).str.zfill(4)
        part["minute_time"] = raw_time.str[:2] + ":" + raw_time.str[2:]
        part["raw_diff"] = part["minute_raw"] - part["daily_raw_implied"]
        part["adjusted_abs_error"] = (part["raw_diff"] * part["adjfactor"]).abs()
        parts.append(part)
    result = pd.concat(parts)
    return result.loc[result["raw_diff"].abs().gt(raw_tolerance)].sort_values(
        "adjusted_abs_error", ascending=False
    )


@dataclass(frozen=True, slots=True)
class PriceConsistencyCheck:
    trade_date: int
    minute_dir: Path
    daily_dir: Path
    raw_tolerance: float = 1e-8

    @property
    def name(self) -> str:
        return "minute_daily_price_consistency"

    def analyze(self) -> tuple[QualityReport, pd.DataFrame, pd.DataFrame]:
        """Return the report plus comparison and mismatch detail tables."""
        comparison, stats = compare_prices(
            self.trade_date, self.minute_dir, self.daily_dir
        )
        mismatches = mismatch_table(comparison, self.raw_tolerance)
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
        report = QualityReport(
            self.name, {"trade_date": self.trade_date, **stats}, tuple(issues)
        )
        return report, comparison, mismatches

    def run(self) -> QualityReport:
        """Run through the generic :class:`QualityCheck` interface."""
        return self.analyze()[0]
