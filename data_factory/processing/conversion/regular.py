"""Conversion of regular pickle objects and passthrough files."""

from __future__ import annotations

import logging
import os
import shutil
from collections import Counter
from pathlib import Path

import pandas as pd

from data_factory.core.layout import minute_relative_dir, target_relative_path
from data_factory.processing.conversion.models import (
    ConversionConfig,
    CopyCounts,
    ObjectKind,
    RegularCounts,
)
from data_factory.processing.conversion.normalization import normalize_daily_matrix

LOG = logging.getLogger(__name__)


def write_parquet_object(source: Path, target: Path, overwrite: bool) -> ObjectKind:
    """Convert one supported pickle object using an atomic target replacement."""
    if target.exists() and not overwrite:
        return ObjectKind.SKIPPED
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
    return ObjectKind.DAILY_WIDE if normalized else ObjectKind.TABLE


def convert_regular_pickles(config: ConversionConfig) -> RegularCounts:
    """Convert all pickle files except the specially handled minute bars."""
    kinds: Counter[ObjectKind] = Counter()
    planned = 0
    minute_root = config.input_root / minute_relative_dir(config.input_root)
    for source in sorted(config.input_root.rglob("*.pkl")):
        if source.is_relative_to(minute_root):
            continue
        relative = source.relative_to(config.input_root)
        target = config.output_root / target_relative_path(relative)
        skipped = target.exists() and not config.overwrite
        if config.dry_run:
            if skipped:
                kinds[ObjectKind.SKIPPED] += 1
                LOG.info("[dry-run] 跳过已有文件: %s", target)
            else:
                planned += 1
                LOG.info("[dry-run] %s -> %s", source, target)
            continue
        kind = write_parquet_object(source, target, config.overwrite)
        kinds[kind] += 1
        LOG.info("%s -> %s (%s)", source, target, kind)
    return RegularCounts.from_kinds(kinds, planned)


def copy_other_files(config: ConversionConfig) -> CopyCounts:
    """Mirror non-pickle files, excluding the minute-bar source directory."""
    copied = 0
    skipped = 0
    minute_root = config.input_root / minute_relative_dir(config.input_root)
    for source in sorted(
        path for path in config.input_root.rglob("*") if path.is_file()
    ):
        if source.suffix == ".pkl" or source.is_relative_to(minute_root):
            continue
        relative = source.relative_to(config.input_root)
        target = config.output_root / target_relative_path(relative)
        if target.exists() and not config.overwrite:
            skipped += 1
            LOG.info("跳过已有文件: %s", target)
            continue
        if config.dry_run:
            LOG.info("[dry-run] 复制 %s -> %s", source, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        copied += 1
    return CopyCounts(copied, skipped)
