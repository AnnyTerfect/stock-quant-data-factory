"""Shared conventions for market-data processing."""

from pathlib import PurePosixPath

MINUTE_FIELDS = ("open", "high", "low", "close", "volume", "amount")
PRICE_FIELDS = frozenset(("open", "high", "low", "close"))
MINUTE_RELATIVE_DIRS = (
    PurePosixPath("market/bars/1m"),
    PurePosixPath("full/market/bars/1m"),
)
