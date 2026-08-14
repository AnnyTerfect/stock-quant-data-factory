"""High-level orchestration API for data conversion."""

from __future__ import annotations

import logging

from data_factory.processing.minute import convert_minute_bars
from data_factory.processing.models import ConversionConfig, ConversionResult
from data_factory.processing.regular import convert_regular_pickles, copy_other_files

LOG = logging.getLogger(__name__)


def convert_dataset(config: ConversionConfig) -> ConversionResult:
    """Run a conversion job and return a structured summary."""
    config = config.validated()
    regular_counts: dict[str, int] = {}
    minute_days = 0
    copied_files = 0
    if config.part in ("all", "regular"):
        regular_counts = convert_regular_pickles(
            config.input_root,
            config.output_root,
            config.overwrite,
            config.dry_run,
        )
        LOG.info("非分钟数据完成: %s", regular_counts)
    if config.part in ("all", "minute"):
        minute_days = convert_minute_bars(
            config.input_root,
            config.output_root,
            config.overwrite,
            config.dry_run,
        )
        LOG.info("分钟数据完成: %d 个交易日", minute_days)
    if config.copy_other:
        copied_files = copy_other_files(
            config.input_root,
            config.output_root,
            config.overwrite,
            config.dry_run,
        )
        LOG.info("复制其他文件完成: %d 个", copied_files)
    return ConversionResult(regular_counts, minute_days, copied_files, config.dry_run)
