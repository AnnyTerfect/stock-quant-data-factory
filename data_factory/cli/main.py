"""Unified command-line interface for Data Factory."""

from __future__ import annotations

import argparse
from collections.abc import Iterable

from data_factory.cli import convert, quality


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="data-factory",
        description="数据处理与数据质量检测工具",
    )
    commands = parser.add_subparsers(
        dest="command",
        title="commands",
        metavar="{convert,check}",
        required=True,
    )

    convert_parser = commands.add_parser(
        "convert", help="转换和标准化数据", description=convert.__doc__
    )
    convert.add_arguments(convert_parser)
    convert_parser.set_defaults(handler=convert.run)

    check_parser = commands.add_parser(
        "check", help="执行数据质量检查", description=quality.__doc__
    )
    quality.add_arguments(check_parser)
    check_parser.set_defaults(handler=quality.run)
    return parser


def main(argv: Iterable[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.handler(args)
