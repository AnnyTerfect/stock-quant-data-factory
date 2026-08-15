"""All disk access for the minute/daily consistency check.

Keeping reads here lets :mod:`.metrics` stay a pure function of dataframes, so
the comparison logic is testable without any fixture files. Where the files sit
is :mod:`data_factory.core.layout`'s business, not this module's.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from data_factory.core.conventions import PRICE_FIELDS
from data_factory.core.layout import (
    DAILY_ADJUSTED_VWAP_FILE,
    DAILY_AMOUNT_FILE,
    DAILY_VOLUME_FILE,
    adjust_factor_file,
    daily_adjusted_price_file,
    daily_relative_dir,
    minute_file_name,
    minute_relative_dir,
)
from data_factory.quality.checks.price_consistency.frames import DailyBundle


def load_minute_day(input_root: Path, trade_date: int) -> pd.DataFrame:
    """Read the long-format minute bars of one trading day."""
    path = input_root / minute_relative_dir(input_root) / minute_file_name(trade_date)
    minute = pd.read_pickle(path)
    if not isinstance(minute, pd.DataFrame):
        raise TypeError(f"{path} 不是 DataFrame")
    return minute


def load_daily_row(path: Path, trade_date: int) -> pd.Series:
    """Read one trading day's row out of a daily matrix."""
    frame = pd.read_pickle(path)
    if not isinstance(frame, pd.DataFrame | pd.Series):
        raise TypeError(f"{path} 不是 DataFrame 或 Series")
    if trade_date not in frame.index:
        raise ValueError(f"{path} 中没有 {trade_date}")
    return frame.loc[trade_date]


def load_daily_bundle(input_root: Path, trade_date: int) -> DailyBundle:
    """Read every daily matrix the consistency check compares against.

    The adjustment factor lives outside the daily-bar directory, so both
    locations are resolved through the layout rules.
    """
    daily_dir = input_root / daily_relative_dir(input_root)
    return DailyBundle(
        trade_date=trade_date,
        adjust_factor=load_daily_row(adjust_factor_file(input_root), trade_date),
        adjusted_prices={
            field: load_daily_row(
                daily_dir / daily_adjusted_price_file(field), trade_date
            )
            for field in PRICE_FIELDS
        },
        volume=load_daily_row(daily_dir / DAILY_VOLUME_FILE, trade_date),
        amount=load_daily_row(daily_dir / DAILY_AMOUNT_FILE, trade_date),
        adjusted_vwap=load_daily_row(daily_dir / DAILY_ADJUSTED_VWAP_FILE, trade_date),
    )
