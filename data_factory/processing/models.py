"""Public request and result models for conversion jobs."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

ConversionPart = Literal["all", "regular", "minute"]


@dataclass(frozen=True, slots=True)
class ConversionConfig:
    """Configuration for one dataset conversion run."""

    input_root: Path = Path("data")
    output_root: Path = Path("data-out")
    part: ConversionPart = "all"
    overwrite: bool = False
    copy_other: bool = False
    dry_run: bool = False

    def validated(self) -> ConversionConfig:
        input_root = self.input_root.resolve()
        output_root = self.output_root.resolve()
        if not input_root.is_dir():
            raise NotADirectoryError(input_root)
        if input_root == output_root:
            raise ValueError("输入与输出目录不能相同")
        return ConversionConfig(
            input_root=input_root,
            output_root=output_root,
            part=self.part,
            overwrite=self.overwrite,
            copy_other=self.copy_other,
            dry_run=self.dry_run,
        )


@dataclass(frozen=True, slots=True)
class ConversionResult:
    """Machine-readable summary returned by :func:`convert_dataset`."""

    regular_counts: dict[str, int] = field(default_factory=dict)
    minute_days: int = 0
    copied_files: int = 0
    dry_run: bool = False
