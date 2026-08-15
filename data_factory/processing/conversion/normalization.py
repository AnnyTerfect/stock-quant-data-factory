"""Pure dataframe normalization functions."""

from __future__ import annotations

import pandas as pd

from data_factory.core.conventions import (
    ensure_unique_dates,
    is_integer_date_axis,
    to_datetime_index,
    unique_symbol_map,
)


def normalize_daily_matrix(frame: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    """Normalize a date-by-symbol matrix; return other tables unchanged.

    The date axis is a *classifier* here, not a precondition: a table whose
    index is not 8-digit days simply is not a daily matrix, and is handed back
    untouched for the caller to write out as it stands.
    """
    if not is_integer_date_axis(frame.index):
        return frame, False
    symbols = unique_symbol_map(frame.columns)
    if not symbols:
        return frame, False

    result = frame.loc[:, list(symbols.values())].copy()
    result.index = to_datetime_index(frame.index)
    result.index.name = "datetime"
    result.columns = pd.Index(list(symbols), dtype="int64", name="stock_code")
    ensure_unique_dates(result.index)
    return result.sort_index(), True
