"""Command-line entry point for dataset conversion."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from data_factory.processing import ConversionConfig, convert_dataset

LOG = logging.getLogger("data-factory.convert")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Register conversion arguments on a command parser."""
    parser.add_argument("--input", type=Path, default=Path("data"), help="源数据根目录")
    parser.add_argument(
        "--output", type=Path, default=Path("data-out"), help="输出根目录"
    )
    parser.add_argument("--log-dir", type=Path, default=Path("logs"), help="日志目录")
    parser.add_argument("--part", choices=("all", "regular", "minute"), default="all")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已有输出文件")
    parser.add_argument("--copy-other", action="store_true", help="复制非 pickle 文件")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅展示转换计划，不读取数据或写入输出",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    return parser


def configure_logging(log_dir: Path) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
    log_path = log_dir / f"convert_data_{timestamp}.log"
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logging.basicConfig(
        level=logging.INFO, handlers=[console, file_handler], force=True
    )
    return log_path


def run(args: argparse.Namespace) -> None:
    """Execute a parsed conversion command."""
    log_path = configure_logging(args.log_dir.resolve())
    LOG.info("日志文件: %s", log_path)
    config = ConversionConfig(
        input_root=args.input,
        output_root=args.output,
        part=args.part,
        overwrite=args.overwrite,
        copy_other=args.copy_other,
        dry_run=args.dry_run,
    )
    convert_dataset(config)


def main(argv: Iterable[str] | None = None) -> None:
    run(build_parser().parse_args(argv))
