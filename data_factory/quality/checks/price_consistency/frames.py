"""In-memory contract between the loading and the computing layer."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True, slots=True)
class DailyBundle:
    """One trading day of daily matrices, each indexed by market symbol."""

    trade_date: int
    adjust_factor: pd.Series
    adjusted_prices: Mapping[str, pd.Series]
    volume: pd.Series
    amount: pd.Series
    adjusted_vwap: pd.Series
