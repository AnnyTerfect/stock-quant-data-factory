"""Command-line entry point for data-quality checks.

The subcommands are generated from the registry, and the report is rendered
without knowing which check produced it, so a newly registered check is
runnable here without any change to this module.
"""

from __future__ import annotations

import argparse

from data_factory.quality import registry
from data_factory.quality.models import QualityReport


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


def _format_metric(value: float | int | str) -> str:
    if isinstance(value, bool | str):  # bool before int: bool is an int subclass
        return str(value)
    if isinstance(value, int):
        return f"{value:,}"
    return f"{value:.6g}"


def render_report(report: QualityReport) -> str:
    """Format a report without knowing which check produced it."""
    lines = [f"[{report.check_name}] 检查结果: {report.status.value}"]
    if report.metrics:
        width = max(len(key) for key in report.metrics)
        lines.append("指标:")
        lines.extend(
            f"  {key:<{width}}  {_format_metric(value)}"
            for key, value in report.metrics.items()
        )
    if report.issues:
        lines.append("问题:")
        lines.extend(
            f"  [{issue.status.value}] {issue.code}: {issue.message}"
            for issue in report.issues
        )
    lines.extend(report.details)
    return "\n".join(lines)
