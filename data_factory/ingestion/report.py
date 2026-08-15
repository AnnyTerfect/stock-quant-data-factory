"""Collecting and presenting what one update run found.

Warnings and errors are captured while they happen but printed together, right
before the confirmation prompt: the answer is a judgement on that list, and a
list printed after the question would mean choosing blind.
"""

from __future__ import annotations

import logging

from data_factory.ingestion.models import UpdateStats

LOG = logging.getLogger(__name__)

#: Every ingestion module logs below this one, so a handler installed here sees
#: the whole run. Spelled out rather than derived, so moving a module cannot
#: silently narrow what gets collected.
PACKAGE_LOGGER = logging.getLogger("data_factory.ingestion")


class IssueLogHandler(logging.Handler):
    """Collect the WARNING / ERROR records of one run for the final summary."""

    def __init__(self, stats: UpdateStats) -> None:
        super().__init__(level=logging.WARNING)
        self.stats = stats

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno >= logging.ERROR:
            level = "ERROR"
        elif record.levelno >= logging.WARNING:
            level = "WARNING"
        else:
            return
        self.stats.issues.append((level, record.getMessage()))


def log_issues(stats: UpdateStats) -> None:
    """Print every warning and error collected, before asking for confirmation."""
    LOG.info(
        "问题汇总: WARNING %d 条, ERROR %d 条", stats.warning_count, stats.error_count
    )
    if not stats.issues:
        LOG.info("未发现不一致、缺失或其他问题")
        return
    for number, (level, message) in enumerate(stats.issues, 1):
        LOG.info("  %d. [%s] %s", number, level, message)


def log_summary(
    stats: UpdateStats, *, changed_files: int, written_files: int, dry_run: bool
) -> None:
    """Print the closing tally of one run."""
    if dry_run:
        suffix = "（dry-run，未落盘）"
    elif stats.error_count:
        suffix = "（校验失败，未落盘）"
    elif not written_files and changed_files:
        suffix = "（用户取消，未落盘）"
    else:
        suffix = ""
    LOG.info(
        "汇总: Barra 覆盖 %d 个（其中历史告警 %d 个）, 日增量包 %d 个, "
        "因子合并 %d 次, 参考快照替换 %d 次, 无匹配跳过 %d 个, 实际写入 %d 个文件%s",
        stats.barra_replaced,
        stats.barra_history_warnings,
        stats.daily_archives,
        stats.factors_merged,
        stats.snapshots_replaced,
        len(stats.unmatched_names),
        written_files,
        suffix,
    )
    if stats.unmatched_names:
        LOG.debug("被跳过的无匹配文件: %s", ", ".join(sorted(stats.unmatched_names)))
