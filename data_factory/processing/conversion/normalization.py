"""Pure dataframe normalization functions."""

from __future__ import annotations

import pandas as pd

from data_factory.core.conventions import unique_symbol_map


def _integer_dates(index: pd.Index) -> pd.Series | None:
    values = pd.Series(index, dtype="object").astype(str)
    if values.empty or not values.str.fullmatch(r"\d{8}").all():
        return None
    return values


def normalize_daily_matrix(frame: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    """Normalize a date-by-symbol matrix; return other tables unchanged."""
    dates = _integer_dates(frame.index)
    if dates is None:
        return frame, False
    symbols = unique_symbol_map(frame.columns)
    if not symbols:
        return frame, False

    result = frame.loc[:, list(symbols.values())].copy()
    result.index = pd.to_datetime(dates.to_numpy(), format="%Y%m%d", errors="raise")
    result.index.name = "datetime"
    result.columns = pd.Index(list(symbols), dtype="int64", name="stock_code")
    if result.index.has_duplicates:
        raise ValueError("日频宽表包含重复日期")
    return result.sort_index(), True
