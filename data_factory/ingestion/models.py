"""Request and result models for update jobs."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from data_factory.core.layout import FULL_ROOT
from data_factory.ingestion.errors import UpdateError


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
