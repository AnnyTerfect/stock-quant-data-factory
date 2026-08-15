"""The vocabulary every subsystem has to agree on: fields, symbols, dates.

``ingestion``, ``processing`` and ``quality`` consume the same upstream
universe, so they must name fields, strip market suffixes and read trading
dates identically; keeping two parsers around let the subsystems disagree about
which columns are stocks and which labels are days.

What lives here is the *spelling* of the vocabulary, not the policy around it:
these functions raise :class:`DateAxisError` and leave each subsystem to decide
whether a malformed axis aborts an update, or merely means "this table is not a
daily matrix".
"""

from __future__ import annotations

import re
from collections.abc import Iterable

import pandas as pd

# ---------------------------------------------------------------------------
# Field names
# ---------------------------------------------------------------------------

# Ordered tuples on purpose: several call sites concatenate per-field arrays and
# compare the results positionally, so the order has to be reproducible.
MINUTE_FIELDS = ("open", "high", "low", "close", "volume", "amount")
PRICE_FIELDS = ("open", "high", "low", "close")

# ---------------------------------------------------------------------------
# Stock symbols
# ---------------------------------------------------------------------------

SYMBOL_RE = re.compile(r"^(\d{6})\.[A-Za-z]{2}$")


def parse_symbol(value: object) -> int | None:
    """Return the numeric code of ``value``, or ``None`` if it is not a symbol."""
    match = SYMBOL_RE.fullmatch(str(value))
    return int(match.group(1)) if match else None


def parse_symbols(values: Iterable[object]) -> list[tuple[object, int]]:
    """Keep the recognizable symbols of ``values`` in their original order."""
    pairs: list[tuple[object, int]] = []
    for value in values:
        code = parse_symbol(value)
        if code is not None:
            pairs.append((value, code))
    return pairs


def unique_symbol_map(values: Iterable[object]) -> dict[int, object]:
    """Map each numeric code to its symbol, rejecting codes claimed twice.

    Insertion order follows the first appearance of each code, so callers can
    reuse it to slice columns without re-sorting.
    """
    grouped: dict[int, list[object]] = {}
    for value, code in parse_symbols(values):
        grouped.setdefault(code, []).append(value)
    ambiguous = {code: names for code, names in grouped.items() if len(names) > 1}
    if ambiguous:
        examples = dict(list(ambiguous.items())[:5])
        raise ValueError(f"股票代码去掉市场后缀后不唯一，例如: {examples}")
    return {code: names[0] for code, names in grouped.items()}


# ---------------------------------------------------------------------------
# Trading dates
# ---------------------------------------------------------------------------

#: Upstream writes trading days as 8-digit integers such as ``20260803``, on
#: file names, on index axes and in long-table columns alike.
DATE_FORMAT = "%Y%m%d"

#: Minute bars label a bar by its start, as ``20260803`` plus ``HHMM``.
MINUTE_FORMAT = "%Y%m%d%H%M"

_INTEGER_DATE_RE = re.compile(r"\d{8}")


class DateAxisError(ValueError):
    """Raised when values do not follow the 8-digit trading-date convention.

    Deliberately a plain :class:`ValueError` subclass: ``core`` has no opinion
    on how bad that is. ``ingestion`` catches it and re-raises an ``UpdateError``
    that aborts the update; ``processing`` catches it to conclude that a table
    simply is not a daily matrix.
    """


def is_integer_date_axis(values: Iterable[object]) -> bool:
    """Whether every value spells a trading day as 8 digits.

    An empty axis is not one: there is nothing to tell a date matrix apart from
    any other empty table, and guessing wrong would rewrite its axes.
    """
    text = pd.Index(values).astype(str)
    return bool(len(text)) and bool(text.str.fullmatch(_INTEGER_DATE_RE).all())


def to_datetime_index(values: Iterable[object]) -> pd.DatetimeIndex:
    """Parse a date axis into a ``DatetimeIndex``.

    Values that already form a ``DatetimeIndex`` are taken as they are, so that
    stringifying first does not turn ``2026-08-03`` into a value that no longer
    matches :data:`DATE_FORMAT`.

    Raises:
        DateAxisError: If any value is not an 8-digit trading day.
    """
    raw = pd.Index(values)
    if isinstance(raw, pd.DatetimeIndex):
        return raw
    dates = pd.to_datetime(raw.astype(str), format=DATE_FORMAT, errors="coerce")
    invalid = raw[pd.isna(dates)]
    if len(invalid):
        raise DateAxisError(f"日期轴含非 YYYYMMDD 值，例如 {invalid[:5].tolist()}")
    return pd.DatetimeIndex(dates)


def to_integer_dates(dates: pd.DatetimeIndex) -> pd.Index:
    """Render a ``DatetimeIndex`` back to the 8-digit integers upstream uses."""
    return pd.Index(dates.strftime(DATE_FORMAT).astype("int64"))


def format_date(date: pd.Timestamp) -> str:
    """Spell one timestamp the way upstream and the logs do."""
    return date.strftime(DATE_FORMAT)


def format_dates(dates: pd.DatetimeIndex, limit: int = 5) -> list[str]:
    """Spell the first ``limit`` dates, for error messages and log lines."""
    return dates[:limit].strftime(DATE_FORMAT).tolist()


def ensure_unique_dates(dates: pd.DatetimeIndex) -> None:
    """Reject a repeated trading day.

    Raises:
        DateAxisError: If any date appears more than once.
    """
    if dates.has_duplicates:
        duplicates = format_dates(dates[dates.duplicated()].unique())
        raise DateAxisError(f"日期轴有重复值，例如 {duplicates}")


def ensure_sorted_dates(dates: pd.DatetimeIndex) -> None:
    """Reject an axis that is not in ascending order.

    Raises:
        DateAxisError: If the dates do not increase monotonically.
    """
    if not dates.is_monotonic_increasing:
        raise DateAxisError("日期轴未按升序排列")
