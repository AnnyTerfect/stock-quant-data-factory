"""Pure comparison logic between aggregated minute bars and daily matrices."""

from __future__ import annotations

import numpy as np
import pandas as pd

from data_factory.core.conventions import PRICE_FIELDS, unique_symbol_map
from data_factory.quality.checks.price_consistency.frames import DailyBundle

VOLUME_SCALE = 10_000
AMOUNT_SCALE = 1_000_000

#: Columns a stock must have before its errors are counted.
REQUIRED_COLUMNS = (
    "adjfactor",
    "daily_volume",
    "daily_amount",
    "daily_adj_vwap",
    *(f"daily_adj_{field}" for field in PRICE_FIELDS),
)


def _safe_median(values: np.ndarray | pd.Series) -> float:
    return float(np.nanmedian(values)) if len(values) else float("nan")


def _safe_quantile(values: np.ndarray, quantile: float) -> float:
    return float(np.nanquantile(values, quantile)) if len(values) else float("nan")


def _safe_max(values: pd.Series) -> float:
    return float(values.max()) if len(values) else float("nan")


def aggregate_minute_prices(
    minute: pd.DataFrame, trade_date: int, label: str = "分钟数据"
) -> pd.DataFrame:
    """Collapse one day of minute bars into a per-stock daily bar."""
    required = {"code", "date", "time", "volume", "amount", *PRICE_FIELDS}
    missing = required.difference(minute.columns)
    if missing:
        raise ValueError(f"{label} 缺少字段: {sorted(missing)}")
    minute = minute.loc[minute["date"].eq(trade_date)].sort_values(
        ["code", "time"], kind="stable"
    )
    if minute.empty:
        raise ValueError(f"{label} 中没有 {trade_date} 的数据")
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


def build_comparison(
    minute_daily: pd.DataFrame, daily: DailyBundle
) -> tuple[pd.DataFrame, list[int]]:
    """Align minute aggregates with daily matrices; also report unmatched codes."""
    symbols = unique_symbol_map(daily.adjust_factor.index)
    minute_daily = minute_daily.copy()
    minute_daily["symbol"] = [symbols.get(int(code)) for code in minute_daily.index]
    unmatched = minute_daily.index[minute_daily["symbol"].isna()].tolist()

    comparison = minute_daily.dropna(subset=["symbol"]).set_index("symbol")
    comparison["adjfactor"] = daily.adjust_factor.reindex(comparison.index)
    for field in PRICE_FIELDS:
        adjusted = daily.adjusted_prices[field].reindex(comparison.index)
        comparison[f"daily_adj_{field}"] = adjusted
        comparison[f"minute_adj_{field}"] = comparison[field] * comparison["adjfactor"]
        comparison[f"daily_raw_{field}"] = adjusted / comparison["adjfactor"]
        comparison[f"raw_diff_{field}"] = (
            comparison[field] - comparison[f"daily_raw_{field}"]
        )

    comparison["daily_volume"] = daily.volume.reindex(comparison.index)
    comparison["daily_amount"] = daily.amount.reindex(comparison.index)
    comparison["daily_adj_vwap"] = daily.adjusted_vwap.reindex(comparison.index)
    comparison["minute_daily_unit_volume"] = comparison["volume"] / VOLUME_SCALE
    comparison["minute_daily_unit_amount"] = comparison["amount"] / AMOUNT_SCALE
    comparison["minute_vwap"] = comparison["amount"] / comparison["volume"]
    comparison["minute_adj_vwap"] = comparison["minute_vwap"] * comparison["adjfactor"]
    comparison["daily_raw_vwap"] = (
        comparison["daily_adj_vwap"] / comparison["adjfactor"]
    )
    return comparison, unmatched


def complete_rows(comparison: pd.DataFrame) -> pd.DataFrame:
    """Rows whose every compared field is present on both sides."""
    return comparison.dropna(subset=list(REQUIRED_COLUMNS)).copy()


def compute_stats(
    minute_daily: pd.DataFrame,
    comparison: pd.DataFrame,
    complete: pd.DataFrame,
    unmatched: list[int],
) -> dict[str, float | int]:
    """Summarize how closely the two sources agree."""
    multiply_errors = np.concatenate(
        [
            (complete[field] * complete["adjfactor"] - complete[f"daily_adj_{field}"])
            .abs()
            .to_numpy()
            for field in PRICE_FIELDS
        ]
    )
    divide_errors = np.concatenate(
        [
            (complete[field] / complete["adjfactor"] - complete[f"daily_adj_{field}"])
            .abs()
            .to_numpy()
            for field in PRICE_FIELDS
        ]
    )
    raw_errors = np.concatenate(
        [complete[f"raw_diff_{field}"].abs().to_numpy() for field in PRICE_FIELDS]
    )
    volume_errors = (
        complete["minute_daily_unit_volume"] - complete["daily_volume"]
    ).abs()
    amount_errors = (
        complete["minute_daily_unit_amount"] - complete["daily_amount"]
    ).abs()
    raw_vwap_errors = (complete["minute_vwap"] - complete["daily_raw_vwap"]).abs()
    return {
        "minute_rows": int(minute_daily["minute_rows"].sum()),
        "minute_codes": len(minute_daily),
        "matched_codes": len(comparison),
        "unmatched_codes": len(unmatched),
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


def mismatch_table(
    comparison: pd.DataFrame, raw_tolerance: float = 1e-8
) -> pd.DataFrame:
    """Per-field rows whose unadjusted price differs beyond ``raw_tolerance``."""
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
