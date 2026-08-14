"""Filesystem conventions for the upstream dataset and the converted output.

Both subsystems locate the same files, so the naming rules live here instead of
being re-derived with inline f-strings at each call site.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

LOG = logging.getLogger(__name__)

#: Layouts that have carried the 1-minute bars, most recent first.
MINUTE_RELATIVE_DIRS = ("market/bars/1m", "full/market/bars/1m")
#: Layouts that have carried the daily matrices, most recent first.
DAILY_RELATIVE_DIRS = ("market/bars/1d", "full/market/bars/1d")
#: The adjustment factor sits outside the daily bar directory.
ADJUST_FACTOR_RELATIVE_PATHS = (
    "market/adjustment/adjfactor.pkl",
    "market/prices/adjfactor.pkl",
    "full/market/adjustment/adjfactor.pkl",
    "full/market/prices/adjfactor.pkl",
)
MINUTE_FILE_RE = re.compile(r"kline_day_(\d{8})\.pkl$")

DAILY_VOLUME_FILE = "volume.pkl"
DAILY_AMOUNT_FILE = "amount.pkl"
DAILY_ADJUSTED_VWAP_FILE = "adj_vwap.pkl"

#: Upstream stem -> canonical stem, grouped by the directory they live in.
_RENAMED_STEMS = {
    "market/adjustment": {"adjfactor": "adj_factor"},
    "market/status": {"trd_status": "trading_status"},
    "market/calendar": {"trd_cal": "trading_calendar"},
    "reference/securities": {"stk_info": "stock_info", "stkcode": "stock_code"},
    "reference/industries": {
        "ind_code_CI": "industry_code_ci",
        "ind_lv1": "industry_l1",
        "ind_lv2": "industry_l2",
        "ind_lv3_NSW": "industry_l3_nsw",
    },
    "barra": {
        "BETA": "beta",
        "SIZE": "size",
        "NLSIZE": "nonlinear_size",
        "MOMENTUM": "momentum",
        "RESVOL": "residual_volatility",
        "LIQUIDITY": "liquidity",
        "EARNINGSYIELD": "earnings_yield",
        "GROWTH": "growth",
        "LEVERAGE": "leverage",
        "BP": "book_to_price",
    },
}


def _build_path_renames() -> dict[str, str]:
    """Expand the stem table into full paths, with and without the ``full/`` prefix."""
    renames: dict[str, str] = {}
    for directory, stems in _RENAMED_STEMS.items():
        for old, new in stems.items():
            for prefix in ("", "full/"):
                renames[f"{prefix}{directory}/{old}.pkl"] = (
                    f"{prefix}{directory}/{new}.parquet"
                )
    return renames


PATH_RENAMES = _build_path_renames()


def minute_file_name(trade_date: int) -> str:
    """Name of the long-format minute-bar pickle for one trading day."""
    return f"kline_day_{trade_date}.pkl"


def minute_file_date(path: Path) -> int | None:
    """Trading day encoded in a minute-bar file name, if it follows the rule."""
    match = MINUTE_FILE_RE.fullmatch(path.name)
    return int(match.group(1)) if match else None


def daily_adjusted_price_file(field: str) -> str:
    """Name of the adjusted daily price matrix for one price field."""
    return f"adj_{field}.pkl"


def target_relative_path(relative: Path) -> Path:
    """Map a source-relative path to its canonical output path."""
    renamed = PATH_RENAMES.get(relative.as_posix())
    if renamed is not None:
        return Path(renamed)
    return relative.with_suffix(".parquet") if relative.suffix == ".pkl" else relative


def minute_relative_dir(input_root: Path) -> Path:
    """Locate the minute-bar directory, falling back to the current layout."""
    for relative in MINUTE_RELATIVE_DIRS:
        if (input_root / relative).is_dir():
            return Path(relative)
    return Path(MINUTE_RELATIVE_DIRS[0])


def daily_relative_dir(input_root: Path) -> Path:
    """Locate the daily-matrix directory, falling back to the current layout."""
    for relative in DAILY_RELATIVE_DIRS:
        if (input_root / relative).is_dir():
            return Path(relative)
    return Path(DAILY_RELATIVE_DIRS[0])


def adjust_factor_file(input_root: Path) -> Path:
    """Locate the daily adjustment-factor matrix across the known layouts."""
    for relative in ADJUST_FACTOR_RELATIVE_PATHS:
        path = input_root / relative
        if path.exists():
            return path
    raise FileNotFoundError(f"{input_root} 下找不到日频复权因子 adjfactor.pkl")


def minute_files(minute_root: Path) -> list[Path]:
    """Minute-bar sources under ``minute_root``, ordered by trading day."""
    dated: list[tuple[int, Path]] = []
    for path in minute_root.glob("*.pkl"):
        date = minute_file_date(path)
        if date is None:
            LOG.warning("忽略不符合分钟文件命名规则的文件: %s", path)
        else:
            dated.append((date, path))
    dated.sort()
    if len({date for date, _ in dated}) != len(dated):
        raise ValueError("分钟文件名中存在重复交易日")
    return [path for _, path in dated]
