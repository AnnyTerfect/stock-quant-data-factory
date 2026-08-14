"""The single rule for turning market symbols into numeric stock codes.

``processing`` and ``quality`` consume the same upstream universe, so they must
strip the market suffix identically; keeping two parsers around let the two
subsystems disagree about which columns are stocks.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

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
