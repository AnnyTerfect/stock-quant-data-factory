"""Terminal rendering that works for any quality report."""

from __future__ import annotations

from data_factory.quality.models import QualityReport


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
