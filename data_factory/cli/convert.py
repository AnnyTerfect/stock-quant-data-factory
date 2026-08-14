"""Command-line entry point for dataset conversion."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from data_factory.processing import ConversionConfig, convert_dataset

LOG = logging.getLogger(__name__)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Register conversion arguments on a command parser."""
    parser.add_argument("--input", type=Path, default=Path("data"), help="源数据根目录")
    parser.add_argument(
        "--output", type=Path, default=Path("data-out"), help="输出根目录"
    )
    parser.add_argument("--part", choices=("all", "regular", "minute"), default="all")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已有输出文件")
    parser.add_argument("--copy-other", action="store_true", help="复制非 pickle 文件")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅展示转换计划，不读取数据或写入输出",
    )


def run(args: argparse.Namespace) -> None:
    """Execute a parsed conversion command."""
    result = convert_dataset(
        ConversionConfig(
            input_root=args.input,
            output_root=args.output,
            part=args.part,
            overwrite=args.overwrite,
            copy_other=args.copy_other,
            dry_run=args.dry_run,
        )
    )
    LOG.info("转换结果: %s", result)
