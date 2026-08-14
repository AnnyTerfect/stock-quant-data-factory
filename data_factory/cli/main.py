"""Unified command-line interface for Data Factory."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Iterable
from pathlib import Path

from data_factory.cli import convert, quality
from data_factory.core.logging import configure_logging

LOG = logging.getLogger(__name__)


def _logging_parser() -> argparse.ArgumentParser:
    """Options every leaf command shares."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--log-dir", type=Path, default=Path("logs"), help="日志目录")
    return common


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="data-factory",
        description="数据处理与数据质量检测工具",
    )
    common = _logging_parser()
    commands = parser.add_subparsers(
        dest="command",
        title="commands",
        metavar="{convert,check}",
        required=True,
    )

    convert_parser = commands.add_parser(
        "convert",
        help="转换和标准化数据",
        description=convert.__doc__,
        parents=[common],
    )
    convert.add_arguments(convert_parser)
    convert_parser.set_defaults(handler=convert.run)

    check_parser = commands.add_parser(
        "check", help="执行数据质量检查", description=quality.__doc__
    )
    quality.add_arguments(check_parser, parents=[common])
    check_parser.set_defaults(handler=quality.run)
    return parser


def main(argv: Iterable[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    log_path = configure_logging(args.log_dir, args.command)
    LOG.info("日志文件: %s", log_path)
    args.handler(args)
