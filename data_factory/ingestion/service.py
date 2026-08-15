"""High-level orchestration API for incremental updates.

One update runs four steps, and the order is not negotiable:

1. index — scan the dataset and map file names to paths;
2. validate and stage — each source checks its input and writes results to the
   staging area, leaving the dataset untouched;
3. summarize and confirm — print every WARNING / ERROR, then ask y/n;
4. commit — once the answer is y, move the staged files into place.

A file that fails validation does not stop the others, and the dataset keeps its
original content until the confirmation.
"""

from __future__ import annotations

import logging
import pickle
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path

from data_factory.core.layout import BARRA_RELATIVE_DIR, minute_relative_dir
from data_factory.ingestion.catalog import build_catalog
from data_factory.ingestion.conventions import (
    BARRA_ARCHIVE_NAME,
    FACTOR_ARCHIVE_NAME,
)
from data_factory.ingestion.date_consistency import validate_recent_dates
from data_factory.ingestion.errors import UpdateError
from data_factory.ingestion.models import UpdateConfig, UpdateStats
from data_factory.ingestion.report import (
    PACKAGE_LOGGER,
    IssueLogHandler,
    log_issues,
    log_summary,
)
from data_factory.ingestion.sources import barra, factor_database
from data_factory.ingestion.staging import StagingArea

LOG = logging.getLogger(__name__)

#: Data problems that a single source can raise without taking the run down.
_RECOVERABLE = (UpdateError, zipfile.BadZipFile, pickle.UnpicklingError, EOFError)


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
        # long-format file per trading day, carry no date axis to merge on, and
        # arrive in a separate archive this flow does not process. Indexing them
        # would make the date-consistency pass read thousands of large files and
        # report every one of them.
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

            try:
                validate_recent_dates(catalog, staging)
            except _RECOVERABLE as error:
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
    except _RECOVERABLE as error:
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
