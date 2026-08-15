"""Factor database: merged day by day.

Delivery shape: ``factorDatabase_incre_pkl.zip`` holds one zip per day
(``factorDatabase_incre_pkl_20260803.zip``…), each carrying a few hundred pickles
under their own directories (``FundData/fund_asset.pkl``…) — far more than the
dataset needs.

The policy is to update only what is already there: the dataset is a subset of
this factor library, so a member applies only when the dataset holds exactly one
file of that name, and everything else is skipped. Skipping is the normal state
here, not a problem.

Unlike Barra, a historical difference is a hard error: the overlapping part of an
increment must equal what is already stored, and a mismatch means an earlier
update went wrong. Merging on would only cement the error.
"""

from __future__ import annotations

import logging
import pickle
import zipfile
from pathlib import Path

from data_factory.ingestion.archives import (
    iter_daily_archives,
    iter_pickle_members,
    member_basename,
)
from data_factory.ingestion.matrix import (
    compare_overlap,
    has_date_axis,
    load_matrix,
    merge,
)
from data_factory.ingestion.models import (
    FULL_SNAPSHOT_FILES,
    Tolerance,
    UpdateError,
    UpdateStats,
)
from data_factory.ingestion.snapshots import validate_snapshot
from data_factory.ingestion.storage import StagingArea, load_pickle

LOG = logging.getLogger(__name__)

#: Failures that concern one file and must not abort the whole daily package.
#: Narrower in scope but wider in type than ``service._RECOVERABLE_SOURCE``: a
#: single member can fail to parse as any shape at all, while a broken archive
#: has already been caught one level up.
_RECOVERABLE_MEMBER = (
    UpdateError,
    pickle.UnpicklingError,
    EOFError,
    TypeError,
    ValueError,
)


def update(
    archive_path: Path,
    catalog: dict[str, Path],
    staging: StagingArea,
    tolerance: Tolerance,
    stats: UpdateStats,
) -> None:
    """Merge everything the increment can match into the staging area, in date order.

    Args:
        archive_path: Path of ``factorDatabase_incre_pkl.zip``.
        catalog: The dataset's whole "file name -> path" index.
        staging: Staging area receiving every merged result.
        tolerance: Float tolerance for comparing overlapping history.
        stats: Running tally.
    """
    if not archive_path.is_file():
        raise UpdateError(f"找不到因子增量压缩包: {archive_path}")

    applied_any = False
    with zipfile.ZipFile(archive_path) as outer:
        for archive_name, daily in iter_daily_archives(outer):
            stats.daily_archives += 1
            LOG.info("=== 日增量包 %s ===", archive_name)
            applied_any |= _apply_daily_archive(
                daily, archive_name, catalog, staging, tolerance, stats
            )

    if stats.unmatched_names:
        LOG.info(
            "增量包中有 %d 个文件在数据目录下没有同名目标，已跳过"
            "（用 --verbose 查看清单）",
            len(stats.unmatched_names),
        )
    if not applied_any:
        raise UpdateError(
            "因子增量包里没有任何文件能匹配数据目录下的目标，请检查交付内容"
        )


def _apply_daily_archive(
    daily: zipfile.ZipFile,
    archive_name: str,
    catalog: dict[str, Path],
    staging: StagingArea,
    tolerance: Tolerance,
    stats: UpdateStats,
) -> bool:
    """Process one daily package; return whether it applied anything."""
    # The package has to be scanned in full first. Applying while iterating would
    # mean the first copy of a duplicated file is already staged by the time the
    # duplicate shows up, and the day could no longer be all-or-nothing.
    matched: list[tuple[zipfile.ZipInfo, str, Path]] = []
    seen: set[str] = set()
    duplicates: set[str] = set()
    for member in iter_pickle_members(daily):
        name = member_basename(member.filename)
        target = catalog.get(name)
        if target is None:
            stats.unmatched_names.add(name)
            continue
        if name in seen:
            duplicates.add(name)
        seen.add(name)
        matched.append((member, name, target))

    if duplicates:
        raise UpdateError(
            f"{archive_name} 里出现重复的目标文件名: {sorted(duplicates)}"
        )

    applied = False
    applied_count = 0

    for member, name, target in matched:
        try:
            if _apply_member(daily, member, name, target, staging, tolerance, stats):
                applied = True
                applied_count += 1
        except _RECOVERABLE_MEMBER as error:
            # One file's failure must not take the daily package with it: the
            # rest goes on, and the error gate at the end decides about the
            # commit. TypeError and ValueError mostly come from pandas when
            # dtypes or indexes disagree, which is equally file-local.
            LOG.error(
                "%s/%s: 处理失败: %s: %s",
                archive_name,
                name,
                type(error).__name__,
                error,
            )
            staging.discard(target)

    LOG.info("%s: 成功应用 %d 个文件", archive_name, applied_count)
    return applied


def _apply_member(
    daily: zipfile.ZipFile,
    member: zipfile.ZipInfo,
    name: str,
    target: Path,
    staging: StagingArea,
    tolerance: Tolerance,
    stats: UpdateStats,
) -> bool:
    """Apply one member to its target; return whether it produced a result."""
    # The crucial part: consecutive daily packages update the same target, so
    # from the second day on the work has to continue from the staged result.
    # The cost is reading and rewriting the whole matrix every day, but memory
    # then depends only on one file rather than accumulating across days.
    source = staging.source_path(target)

    if name in FULL_SNAPSHOT_FILES:
        return _replace_snapshot(daily, member, name, target, source, staging, stats)
    return _merge_matrix(daily, member, name, target, source, staging, tolerance, stats)


def _replace_snapshot(
    daily: zipfile.ZipFile,
    member: zipfile.ZipInfo,
    name: str,
    target: Path,
    source: Path,
    staging: StagingArea,
    stats: UpdateStats,
) -> bool:
    """Reference snapshot: replaced as a whole once its structure checks out."""
    local = load_pickle(source)
    with daily.open(member) as stream:
        incoming = load_pickle(stream)

    validate_snapshot(local, incoming, name)
    staging.stage_object(target, incoming)
    stats.snapshots_replaced += 1
    LOG.info("%s: 按全量快照整体替换", name)
    return True


def _merge_matrix(
    daily: zipfile.ZipFile,
    member: zipfile.ZipInfo,
    name: str,
    target: Path,
    source: Path,
    staging: StagingArea,
    tolerance: Tolerance,
    stats: UpdateStats,
) -> bool:
    """Factor matrix: merge new dates and symbols once the overlap agrees."""
    local = load_matrix(source, f"{name}（本地）")
    with daily.open(member) as stream:
        incoming = load_matrix(stream, f"{name}（输入）")

    # What is not a date matrix cannot be merged by date. Skipped rather than
    # failed: such a file is most likely a new reference table, and what it needs
    # is a snapshot rule, not a whole delivery held up.
    for frame, side in ((local, "本地"), (incoming, "输入")):
        if not has_date_axis(frame.index):
            LOG.warning(
                "%s: %s的行索引不像 YYYYMMDD 日期轴（例 %s），"
                "本次跳过；若它是全量参考表，请加进 FULL_SNAPSHOT_FILES",
                name,
                side,
                frame.index[:3].tolist(),
            )
            return False

    report = compare_overlap(local, incoming, name, tolerance)
    if report.mismatches:
        # The overlap of an increment must agree with the dataset; a difference
        # means the baseline data is already wrong.
        LOG.error("%s", report.mismatch_message(name))

    staging.stage_object(target, merge(local, incoming, name))
    stats.factors_merged += 1
    return True
