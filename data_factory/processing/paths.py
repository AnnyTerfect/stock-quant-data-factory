"""Source discovery and output naming rules."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from data_factory.processing.constants import MINUTE_RELATIVE_DIRS

LOG = logging.getLogger(__name__)
MINUTE_FILE_RE = re.compile(r"kline_day_(\d{8})\.pkl$")

PATH_RENAMES = {
    "full/market/adjustment/adjfactor.pkl": "full/market/adjustment/adj_factor.parquet",
    "full/market/status/trd_status.pkl": "full/market/status/trading_status.parquet",
    "full/market/calendar/trd_cal.pkl": "full/market/calendar/trading_calendar.parquet",
    "full/reference/securities/stk_info.pkl": "full/reference/securities/stock_info.parquet",
    "full/reference/securities/stkcode.pkl": "full/reference/securities/stock_code.parquet",
    "full/reference/industries/ind_code_CI.pkl": "full/reference/industries/industry_code_ci.parquet",
    "full/reference/industries/ind_lv1.pkl": "full/reference/industries/industry_l1.parquet",
    "full/reference/industries/ind_lv2.pkl": "full/reference/industries/industry_l2.parquet",
    "full/reference/industries/ind_lv3_NSW.pkl": "full/reference/industries/industry_l3_nsw.parquet",
}

_BARRA_NAMES = {
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
}
for _old_name, _new_name in _BARRA_NAMES.items():
    PATH_RENAMES[f"full/barra/{_old_name}.pkl"] = f"full/barra/{_new_name}.parquet"
for _source, _target in list(PATH_RENAMES.items()):
    if _source.startswith("full/"):
        PATH_RENAMES[_source.removeprefix("full/")] = _target.removeprefix("full/")


def target_relative_path(relative: Path) -> Path:
    """Map a source-relative path to its canonical output path."""
    renamed = PATH_RENAMES.get(relative.as_posix())
    if renamed is not None:
        return Path(renamed)
    return relative.with_suffix(".parquet") if relative.suffix == ".pkl" else relative


def minute_relative_dir(input_root: Path) -> Path:
    for relative in MINUTE_RELATIVE_DIRS:
        path = Path(relative.as_posix())
        if (input_root / path).is_dir():
            return path
    return Path(MINUTE_RELATIVE_DIRS[0].as_posix())


def minute_files(minute_root: Path) -> list[Path]:
    dated: list[tuple[int, Path]] = []
    for path in minute_root.glob("*.pkl"):
        match = MINUTE_FILE_RE.fullmatch(path.name)
        if match:
            dated.append((int(match.group(1)), path))
        else:
            LOG.warning("忽略不符合分钟文件命名规则的文件: %s", path)
    dated.sort()
    if len({date for date, _ in dated}) != len(dated):
        raise ValueError("分钟文件名中存在重复交易日")
    return [path for _, path in dated]
