"""High-level orchestration API for data conversion."""

from __future__ import annotations

import logging

from data_factory.processing.conversion.minute import convert_minute_bars
from data_factory.processing.conversion.models import (
    ConversionConfig,
    ConversionResult,
    CopyCounts,
    RegularCounts,
)
from data_factory.processing.conversion.regular import (
    convert_regular_pickles,
    copy_other_files,
)

LOG = logging.getLogger(__name__)


def convert_dataset(config: ConversionConfig) -> ConversionResult:
    """Run a conversion job and return a structured summary."""
    config = config.validated()
    regular = RegularCounts()
    minute_days = 0
    copied = CopyCounts()
    if config.part in ("all", "regular"):
        regular = convert_regular_pickles(config)
        LOG.info("非分钟数据完成: %s", regular)
    if config.part in ("all", "minute"):
        minute_days = convert_minute_bars(config)
        LOG.info("分钟数据完成: %d 个交易日", minute_days)
    if config.copy_other:
        copied = copy_other_files(config)
        LOG.info("复制其他文件完成: %s", copied)
    return ConversionResult(regular, minute_days, copied, config.dry_run)
