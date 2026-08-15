"""What one update run is told, what it is allowed to assume, and what it reports.

Three kinds of thing that only ever change together, and that everything else in
the package depends on:

* :class:`UpdateError`, the one exception the flow raises;
* the delivery conventions and thresholds — adapting to a new delivery
  structure should start, and preferably end, in the block below;
* :class:`Tolerance` / :class:`UpdateConfig` / :class:`UpdateStats`.

Names of the local dataset itself are not repeated here: they come from
:mod:`data_factory.core.layout`, which every subsystem already agrees on.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from data_factory.core.layout import (
    FULL_ROOT,
    INDUSTRY_CODE_FILE,
    STOCK_CODE_FILE,
    STOCK_INFO_FILE,
    TRADING_CALENDAR_FILE,
)


class UpdateError(RuntimeError):
    """Raised when the data cannot be updated safely.

    It separates "the data is wrong" from "the program is wrong": the command
    line turns an :class:`UpdateError` into one concise line plus a non-zero
    exit code, while every other exception keeps its traceback.
    """


# ---------------------------------------------------------------------------
# Archive names inside one delivery directory (e.g. data/incremental/2026-08-08)
# ---------------------------------------------------------------------------

#: Barra risk factors: every delivery carries the full history and overwrites.
BARRA_ARCHIVE_NAME = "barra.zip"

#: Factor database increments: one inner zip per day, merged in date order.
FACTOR_ARCHIVE_NAME = "factorDatabase_incre_pkl.zip"

#: Minute bars: one long-format pickle per trading day, added day by day.
MINUTE_ARCHIVE_NAME = "Kline_incre.zip"

# ---------------------------------------------------------------------------
# Local dataset conventions
# ---------------------------------------------------------------------------

#: Files delivered as a full snapshot rather than an increment: no date merge,
#: they replace the local copy once the structural checks pass.
FULL_SNAPSHOT_FILES = frozenset(
    {TRADING_CALENDAR_FILE, STOCK_CODE_FILE, STOCK_INFO_FILE}
)

#: Reference files without a date axis; they sit out the date-consistency pass.
NON_DATE_FILES = frozenset({STOCK_CODE_FILE, STOCK_INFO_FILE, INDUSTRY_CODE_FILE})

#: Calendar and look-back window used by the global date-consistency pass.
DATE_REFERENCE_FILE = TRADING_CALENDAR_FILE
DATE_CONSISTENCY_DAYS = 1000

#: How many trading days a matrix may trail the calendar by. Some upstream files
#: (universe, for one) are always published a beat after the bars; as long as the
#: covered range matches the calendar exactly, a small lag only warns.
MAX_DATE_LAG_DAYS = 5

# ---------------------------------------------------------------------------
# Archive resource limits
# ---------------------------------------------------------------------------

# These caps do not judge whether the data is correct; they keep a corrupt or
# hostile archive from exhausting memory and disk before any check runs. The
# values sit deliberately above normal delivery size — raising them should
# follow from inspecting the delivery, not from hitting the limit.
MAX_ARCHIVE_MEMBERS = 20_000
MAX_ARCHIVE_MEMBER_BYTES = 8 * 1024**3
MAX_ARCHIVE_TOTAL_BYTES = 128 * 1024**3
MAX_COMPRESSION_RATIO = 1_000
MAX_INNER_ARCHIVE_BYTES = 8 * 1024**3

# ---------------------------------------------------------------------------
# Comparison parameters
# ---------------------------------------------------------------------------

#: Stock columns compared per chunk. Column counts run in the thousands, and
#: chunking keeps the intermediate matrices at tens of MB instead of copying the
#: whole frame just to compare it.
COLUMN_CHUNK_SIZE = 128

#: How many differing cells to print; enough to locate the problem, not a flood.
MISMATCH_EXAMPLE_LIMIT = 8


# ---------------------------------------------------------------------------
# Request and result models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Tolerance:
    """Float tolerance for comparing overlapping history.

    Passed around as one object so the two bare numbers never drift apart on
    their way down the call stack.
    """

    rtol: float = 1e-7
    atol: float = 1e-7

    def validated(self) -> Tolerance:
        if not (math.isfinite(self.rtol) and math.isfinite(self.atol)):
            raise UpdateError("rtol 和 atol 必须是非负有限数")
        if self.rtol < 0 or self.atol < 0:
            raise UpdateError("rtol 和 atol 必须是非负有限数")
        return self


@dataclass(frozen=True, slots=True)
class UpdateConfig:
    """Configuration for one incremental update run."""

    #: Delivery directory holding the archives, e.g. ``data/incremental/2026-08-08``.
    delivery_dir: Path
    #: The local full history to update in place.
    data_root: Path = FULL_ROOT
    tolerance: Tolerance = Tolerance()
    dry_run: bool = False
    #: Unpickling executes code, so trusting the delivery has to be deliberate.
    trusted_pickle: bool = False

    def validated(self) -> UpdateConfig:
        delivery_dir = self.delivery_dir.expanduser().resolve()
        data_root = self.data_root.expanduser().resolve()
        if not delivery_dir.is_dir():
            raise UpdateError(f"交付目录不存在: {delivery_dir}")
        if not data_root.is_dir():
            raise UpdateError(f"数据目录不存在: {data_root}")
        if not self.trusted_pickle:
            raise UpdateError(
                "交付物包含可执行的 pickle; 仅确认来源可信后才能处理"
                "（命令行传 --trusted-pickle）"
            )
        return UpdateConfig(
            delivery_dir=delivery_dir,
            data_root=data_root,
            tolerance=self.tolerance.validated(),
            dry_run=self.dry_run,
            trusted_pickle=self.trusted_pickle,
        )


#: Counters a failed source has to give back. ``daily_archives`` and
#: ``unmatched_names`` describe what was read, not what will be written, so
#: rolling them back would hide work that really happened.
_SOURCE_COUNTERS = (
    "barra_replaced",
    "barra_history_warnings",
    "factors_merged",
    "snapshots_replaced",
    "minute_days_added",
)


@dataclass
class UpdateStats:
    """Running tally of one update, returned by :func:`update_dataset`.

    Unlike the conversion result this is filled in as the run proceeds: the
    confirmation prompt and the error gate both read it before the run ends.
    """

    issues: list[tuple[str, str]] = field(default_factory=list)
    """Every WARNING / ERROR seen during the run, in the order they occurred."""

    barra_replaced: int = 0
    """Barra factor files staged for a full overwrite."""

    barra_history_warnings: int = 0
    """Barra files whose history disagreed but which are overwritten anyway."""

    factors_merged: int = 0
    """Factor matrix merges (one file updated on several days counts several)."""

    snapshots_replaced: int = 0
    """Full reference snapshots replaced wholesale."""

    daily_archives: int = 0
    """Daily increment archives processed."""

    minute_days_added: int = 0
    """Minute-bar trading days staged as new files."""

    minute_days_verified: int = 0
    """Delivered minute days the dataset already held, kept after comparing."""

    unmatched_names: set[str] = field(default_factory=set)
    """Delivered names with no same-named target in the dataset, hence skipped."""

    @property
    def error_count(self) -> int:
        return sum(level == "ERROR" for level, _ in self.issues)

    @property
    def warning_count(self) -> int:
        return sum(level == "WARNING" for level, _ in self.issues)

    def counters(self) -> dict[str, int]:
        """Snapshot of the counters that belong to a single source."""
        return {name: getattr(self, name) for name in _SOURCE_COUNTERS}

    def restore(self, counters: Mapping[str, int]) -> None:
        """Undo the counters of a source whose staged results were discarded."""
        for name, value in counters.items():
            setattr(self, name, value)
