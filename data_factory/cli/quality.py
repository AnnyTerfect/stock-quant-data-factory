"""Command-line entry point for data-quality checks.

The subcommands are generated from the registry, so a newly registered check is
runnable here without any change to this module.
"""

from __future__ import annotations

import argparse

from data_factory.cli.render import render_report
from data_factory.quality import registry


def add_arguments(
    parser: argparse.ArgumentParser,
    parents: list[argparse.ArgumentParser] | None = None,
) -> None:
    """Register one subcommand per known check."""
    checks = parser.add_subparsers(
        dest="check_name", title="checks", metavar="CHECK", required=True
    )
    for spec in registry.specs():
        check_parser = checks.add_parser(
            spec.name,
            help=spec.summary,
            description=f"{spec.summary}（数据范围: {spec.scope.value}）",
            parents=parents or [],
        )
        for option in spec.options:
            check_parser.add_argument(
                option.command_flag,
                dest=option.name,
                type=option.type,
                default=option.default,
                help=option.help,
            )
        check_parser.set_defaults(spec=spec)


def run(args: argparse.Namespace) -> None:
    """Execute a parsed quality-check command."""
    spec = args.spec
    values = {option.name: getattr(args, option.name) for option in spec.options}
    print(render_report(spec.build(values).run()))
