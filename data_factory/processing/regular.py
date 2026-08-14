"""Conversion of regular pickle objects and passthrough files."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

import pandas as pd

from data_factory.processing.normalization import normalize_daily_matrix
from data_factory.processing.paths import minute_relative_dir, target_relative_path

LOG = logging.getLogger(__name__)


def write_parquet_object(source: Path, target: Path, overwrite: bool) -> str:
    """Convert one supported pickle object using an atomic target replacement."""
    if target.exists() and not overwrite:
        return "skipped"
    value = pd.read_pickle(source)
    if isinstance(value, pd.Series):
        value = value.to_frame(name=value.name if value.name is not None else "value")
    if not isinstance(value, pd.DataFrame):
        raise TypeError(f"不支持的 pickle 对象类型: {type(value).__name__}")

    value, normalized = normalize_daily_matrix(value)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    try:
        value.to_parquet(temporary, engine="pyarrow", compression="zstd", index=True)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return "daily-wide" if normalized else "table"


def convert_regular_pickles(
    input_root: Path,
    output_root: Path,
    overwrite: bool = False,
    dry_run: bool = False,
) -> dict[str, int]:
    """Convert all pickle files except the specially handled minute bars."""
    counts = {"daily-wide": 0, "table": 0, "skipped": 0}
    if dry_run:
        counts["planned"] = 0
    minute_root = input_root / minute_relative_dir(input_root)
    for source in sorted(input_root.rglob("*.pkl")):
        if source.is_relative_to(minute_root):
            continue
        target = output_root / target_relative_path(source.relative_to(input_root))
        if dry_run:
            if target.exists() and not overwrite:
                counts["skipped"] += 1
                LOG.info("[dry-run] 跳过已有文件: %s", target)
            else:
                counts["planned"] += 1
                LOG.info("[dry-run] %s -> %s", source, target)
            continue
        kind = write_parquet_object(source, target, overwrite)
        counts[kind] += 1
        LOG.info("%s -> %s (%s)", source, target, kind)
    return counts


def copy_other_files(
    input_root: Path,
    output_root: Path,
    overwrite: bool = False,
    dry_run: bool = False,
) -> int:
    """Mirror non-pickle files, excluding the minute-bar source directory."""
    copied = 0
    minute_root = input_root / minute_relative_dir(input_root)
    for source in sorted(path for path in input_root.rglob("*") if path.is_file()):
        if source.suffix == ".pkl" or source.is_relative_to(minute_root):
            continue
        target = output_root / target_relative_path(source.relative_to(input_root))
        if target.exists() and not overwrite:
            continue
        if dry_run:
            LOG.info("[dry-run] 复制 %s -> %s", source, target)
            copied += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied += 1
    return copied
