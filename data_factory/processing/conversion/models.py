"""Request and result models for conversion jobs."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Literal

from data_factory.core.layout import FULL_ROOT, OUTPUT_ROOT

ConversionPart = Literal["all", "regular", "minute"]


class ObjectKind(StrEnum):
    """What happened to one regular pickle."""

    DAILY_WIDE = "daily-wide"
    TABLE = "table"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class ConversionConfig:
    """Configuration for one dataset conversion run."""

    input_root: Path = FULL_ROOT
    output_root: Path = OUTPUT_ROOT
    part: ConversionPart = "all"
    overwrite: bool = False
    copy_other: bool = False
    dry_run: bool = False
    workers: int | None = None

    def validated(self) -> ConversionConfig:
        input_root = self.input_root.resolve()
        output_root = self.output_root.resolve()
        if not input_root.is_dir():
            raise NotADirectoryError(input_root)
        if input_root == output_root:
            raise ValueError("输入与输出目录不能相同")
        if self.workers is not None and self.workers < 1:
            raise ValueError("workers 必须大于 0")
        return ConversionConfig(
            input_root=input_root,
            output_root=output_root,
            part=self.part,
            overwrite=self.overwrite,
            copy_other=self.copy_other,
            dry_run=self.dry_run,
            workers=self.workers,
        )


@dataclass(frozen=True, slots=True)
class RegularCounts:
    """Outcome tally for the regular-pickle pass.

    Every field is always present, so callers never have to guess which keys a
    dry run happens to produce.
    """

    daily_wide: int = 0
    table: int = 0
    skipped: int = 0
    planned: int = 0

    @classmethod
    def from_kinds(cls, kinds: Counter[ObjectKind], planned: int = 0) -> RegularCounts:
        return cls(
            daily_wide=kinds[ObjectKind.DAILY_WIDE],
            table=kinds[ObjectKind.TABLE],
            skipped=kinds[ObjectKind.SKIPPED],
            planned=planned,
        )


@dataclass(frozen=True, slots=True)
class CopyCounts:
    """Outcome tally for the passthrough-copy pass."""

    copied: int = 0
    skipped: int = 0


@dataclass(frozen=True, slots=True)
class ConversionResult:
    """Machine-readable summary returned by :func:`convert_dataset`."""

    regular: RegularCounts = field(default_factory=RegularCounts)
    minute_days: int = 0
    copied: CopyCounts = field(default_factory=CopyCounts)
    dry_run: bool = False
