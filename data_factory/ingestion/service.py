"""High-level orchestration API for incremental updates.

One update runs four steps, and the order is not negotiable:

1. index — scan the dataset and map file names to paths;
2. validate and stage — each source checks its input and writes results to the
   staging area, leaving the dataset untouched;
3. summarize and confirm — print every WARNING / ERROR, then ask y/n;
4. commit — once the answer is y, move the staged files into place.

A file that fails validation does not stop the others, and the dataset keeps its
original content until the confirmation.

Step 3 is why the reporting helpers live here too: warnings and errors are
captured while they happen but printed together, right before the prompt, since
the answer is a judgement on that list and a list printed after the question
would mean choosing blind.
"""

from __future__ import annotations

import logging
import pickle
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path

from data_factory.core.layout import BARRA_RELATIVE_DIR, minute_relative_dir
from data_factory.ingestion.date_consistency import validate_recent_dates
from data_factory.ingestion.models import (
    BARRA_ARCHIVE_NAME,
    FACTOR_ARCHIVE_NAME,
    MINUTE_ARCHIVE_NAME,
    UpdateConfig,
    UpdateError,
    UpdateStats,
)
from data_factory.ingestion.sources import barra, factor_database, minute_bars
from data_factory.ingestion.storage import StagingArea, build_catalog

LOG = logging.getLogger(__name__)

#: Every ingestion module logs below this one, so a handler installed here sees
#: the whole run. Spelled out rather than derived, so moving a module cannot
#: silently narrow what gets collected.
PACKAGE_LOGGER = logging.getLogger("data_factory.ingestion")

#: Data problems a whole source can raise without taking the run down. Wider
#: than the per-member tuple in ``sources.factor_database``: at this level a
#: broken archive is one failed source, not a failed run.
_RECOVERABLE_SOURCE = (
    UpdateError,
    zipfile.BadZipFile,
    pickle.UnpicklingError,
    EOFError,
)


def update_dataset(
    config: UpdateConfig, confirm: Callable[[str], str] | None = None
) -> UpdateStats:
    """Run one update job and return its tally.

    Args:
        config: What to apply, to which dataset, and how strictly.
        confirm: Optional input function, mainly for tests; defaults to ``input``.
    """
    config = config.validated()
    LOG.info("交付目录: %s", config.delivery_dir)
    LOG.info("数据目录: %s", config.data_root)

    stats = UpdateStats()
    issue_handler = IssueLogHandler(stats)
    PACKAGE_LOGGER.addHandler(issue_handler)
    changed_files = 0
    written_files = 0
    try:
        # Minute bars are left out of the index on purpose: they are one
        # long-format file per trading day, so they are matched by the date in
        # their name rather than by a catalog of existing names. Indexing them
        # would also make the date-consistency pass read thousands of large
        # files and report every one of them; ``minute_bars`` checks their
        # trading days from the file names instead.
        minute_root = config.data_root / minute_relative_dir(config.data_root)
        catalog = build_catalog(config.data_root, skip=[minute_root])

        # The staging directory sits next to the dataset so that every single
        # os.replace stays within one filesystem.
        with tempfile.TemporaryDirectory(
            prefix=".data-factory-update-", dir=config.data_root.parent
        ) as temporary:
            staging = StagingArea(Path(temporary), config.data_root)
            barra_dir = config.data_root / BARRA_RELATIVE_DIR

            _run_source(
                "Barra",
                staging,
                stats,
                lambda: barra.update(
                    archive_path=config.delivery_dir / BARRA_ARCHIVE_NAME,
                    barra_dir=barra_dir,
                    staging=staging,
                    tolerance=config.tolerance,
                    stats=stats,
                ),
            )

            # The Barra directory belongs to barra.zip alone, so a coincidentally
            # same-named file in the factor library cannot overwrite it twice.
            factor_catalog = {
                name: target
                for name, target in catalog.items()
                if not target.is_relative_to(barra_dir)
            }
            _run_source(
                "因子增量",
                staging,
                stats,
                lambda: factor_database.update(
                    archive_path=config.delivery_dir / FACTOR_ARCHIVE_NAME,
                    catalog=factor_catalog,
                    staging=staging,
                    tolerance=config.tolerance,
                    stats=stats,
                ),
            )

            # After the factor increments, so that the day sequence is checked
            # against the calendar this delivery brings rather than the old one.
            _run_source(
                "分钟行情",
                staging,
                stats,
                lambda: minute_bars.update(
                    archive_path=config.delivery_dir / MINUTE_ARCHIVE_NAME,
                    minute_dir=minute_root,
                    catalog=catalog,
                    staging=staging,
                    stats=stats,
                ),
            )

            try:
                validate_recent_dates(catalog, staging)
            except _RECOVERABLE_SOURCE as error:
                LOG.error("全局日期校验失败: %s", error)

            changed_files = len(staging)
            # The issue list has to precede the y/n prompt: the answer is a
            # judgement on that list, and printing it afterwards would mean
            # choosing blind. No new WARNING / ERROR is produced from here on.
            PACKAGE_LOGGER.removeHandler(issue_handler)
            log_issues(stats)
            if stats.error_count:
                LOG.info(
                    "存在 %d 条 ERROR，禁止提交；数据目录未写入任何文件",
                    stats.error_count,
                )
            elif config.dry_run:
                LOG.info("dry-run: %d 个文件已生成待合并结果，未写入", changed_files)
            elif changed_files and _confirm_merge(confirm):
                staging.commit()
                written_files = changed_files
            elif changed_files:
                LOG.info("用户取消合并，数据目录未写入任何文件")
            else:
                LOG.info("没有可合并的文件，数据目录未写入任何文件")
    finally:
        PACKAGE_LOGGER.removeHandler(issue_handler)

    log_summary(
        stats,
        changed_files=changed_files,
        written_files=written_files,
        dry_run=config.dry_run,
    )
    return stats


def _run_source(
    label: str,
    staging: StagingArea,
    stats: UpdateStats,
    action: Callable[[], None],
) -> None:
    """Run one source, discarding all of its candidates if it reports any error."""
    checkpoint = staging.checkpoint()
    errors_before = stats.error_count
    counters_before = stats.counters()
    try:
        action()
    except _RECOVERABLE_SOURCE as error:
        LOG.error("%s处理失败: %s", label, error)
    if stats.error_count > errors_before:
        staging.rollback(checkpoint)
        stats.restore(counters_before)
        LOG.info("%s存在错误，已撤销该数据源的全部暂存结果", label)


def _confirm_merge(confirm: Callable[[str], str] | None) -> bool:
    """Accept only an explicit y/n; unreadable input counts as n."""
    ask = confirm or input
    while True:
        try:
            answer = ask("是否合并以上待更新文件？[y/n]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            LOG.info("未收到确认，按 n 处理")
            return False
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no", ""}:
            return False
        LOG.warning("请输入 y 或 n")


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
        "因子合并 %d 次, 参考快照替换 %d 次, 分钟行情新增 %d 个交易日"
        "（已有且一致 %d 个）, 无匹配跳过 %d 个, 实际写入 %d 个文件%s",
        stats.barra_replaced,
        stats.barra_history_warnings,
        stats.daily_archives,
        stats.factors_merged,
        stats.snapshots_replaced,
        stats.minute_days_added,
        stats.minute_days_verified,
        len(stats.unmatched_names),
        written_files,
        suffix,
    )
    if stats.unmatched_names:
        LOG.debug("被跳过的无匹配文件: %s", ", ".join(sorted(stats.unmatched_names)))
