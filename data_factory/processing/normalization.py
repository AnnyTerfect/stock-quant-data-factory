"""Pure dataframe normalization functions."""

from __future__ import annotations

import re

import pandas as pd

SYMBOL_RE = re.compile(r"^(\d{6})\.[A-Za-z]{2}$")


def _integer_dates(index: pd.Index) -> pd.Series | None:
    values = pd.Series(index, dtype="object").astype(str)
    if values.empty or not values.str.fullmatch(r"\d{8}").all():
        return None
    return values


def normalize_daily_matrix(frame: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    """Normalize a date-by-symbol matrix; return other tables unchanged."""
    dates = _integer_dates(frame.index)
    parsed_columns: list[tuple[object, int]] = []
    for column in frame.columns:
        match = SYMBOL_RE.fullmatch(str(column))
        if match:
            parsed_columns.append((column, int(match.group(1))))
    if dates is None or not parsed_columns:
        return frame, False

    numeric_codes = [code for _, code in parsed_columns]
    duplicates = pd.Index(numeric_codes).duplicated(keep=False)
    if duplicates.any():
        repeated = sorted(set(pd.Index(numeric_codes)[duplicates].tolist()))
        raise ValueError(f"股票代码去掉交易所后不唯一: {repeated[:10]}")

    result = frame.loc[:, [column for column, _ in parsed_columns]].copy()
    result.index = pd.to_datetime(dates.to_numpy(), format="%Y%m%d", errors="raise")
    result.index.name = "datetime"
    result.columns = pd.Index(numeric_codes, dtype="int64", name="stock_code")
    if result.index.has_duplicates:
        raise ValueError("日频宽表包含重复日期")
    return result.sort_index(), True
