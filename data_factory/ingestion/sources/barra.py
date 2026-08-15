"""Barra risk factors: full overwrite.

Delivery shape: ``barra.zip`` holds a dozen ``<factor>.pkl`` files, each a
complete history, matching the same-named files under the dataset's ``barra/``.

The policy is overwrite rather than merge, because the vendor re-estimates the
whole history every period and historical values are genuinely expected to move.
So value differences only warn; structural problems — lost dates, a shrunken
universe, duplicate labels, a file count that does not line up — say the delivery
itself is wrong and are reported as errors.
"""

from __future__ import annotations

import logging
import pickle
import zipfile
from pathlib import Path

from data_factory.ingestion.archives import (
    iter_pickle_members,
    member_basename,
    validate_archive_limits,
)
from data_factory.ingestion.catalog import build_catalog
from data_factory.ingestion.errors import UpdateError
from data_factory.ingestion.matrix import (
    compare_overlap,
    ensure_covers_local_dates,
    ensure_covers_local_stocks,
    load_matrix,
)
from data_factory.ingestion.models import Tolerance, UpdateStats
from data_factory.ingestion.staging import StagingArea

LOG = logging.getLogger(__name__)


def update(
    archive_path: Path,
    barra_dir: Path,
    staging: StagingArea,
    tolerance: Tolerance,
    stats: UpdateStats,
) -> None:
    """Validate ``barra.zip`` and register its files in the staging area."""
    if not archive_path.is_file():
        raise UpdateError(f"找不到 Barra 压缩包: {archive_path}")
    if not barra_dir.is_dir():
        raise UpdateError(f"找不到本地 Barra 目录: {barra_dir}")

    # Indexing the Barra directory itself rather than the whole dataset is what
    # makes the closing check possible: every local factor must be in the
    # delivery.
    local_files = build_catalog(barra_dir)
    LOG.info(
        "Barra: 开始处理 %s（本地 %d 个因子）", archive_path.name, len(local_files)
    )

    delivered: set[str] = set()
    with zipfile.ZipFile(archive_path) as archive:
        validate_archive_limits(archive, archive_path.name)
        members = list(iter_pickle_members(archive))
        if not members:
            raise UpdateError(f"{archive_path} 里没有任何 pickle 文件")

        for member in members:
            try:
                name = member_basename(member.filename)
            except UpdateError as error:
                LOG.error("%s", error)
                continue
            if name in delivered:
                LOG.error("Barra 压缩包里出现重复文件名: %s", name)
                continue
            delivered.add(name)

            target = local_files.get(name)
            if target is None:
                LOG.error("Barra 输入 %s 在 %s 下没有对应文件", name, barra_dir)
                continue

            try:
                _check_one(archive, member, name, target, staging, tolerance, stats)
            except (UpdateError, pickle.UnpicklingError) as error:
                LOG.error("%s", error)
                staging.discard(target)

    missing = sorted(set(local_files) - delivered)
    if missing:
        LOG.error("Barra 全量包缺少本地已有的因子: %s", missing)


def _check_one(
    archive: zipfile.ZipFile,
    member: zipfile.ZipInfo,
    name: str,
    target: Path,
    staging: StagingArea,
    tolerance: Tolerance,
    stats: UpdateStats,
) -> None:
    """Validate one Barra factor and register the delivered file for writing."""
    label = f"Barra/{name}"

    # Extracted into the staging area before being read, rather than unpickled
    # straight from the stream: the raw file is what will overwrite the local one
    # anyway (no need to re-serialize), and at hundreds of MB per file this keeps
    # the decompression buffer and the deserialized frame out of memory together.
    with archive.open(member) as stream:
        staged = staging.stage_stream(target, stream)

    local_frame = load_matrix(target, f"{label}（本地）")
    incoming_frame = load_matrix(staged, f"{label}（输入）")

    # An overwrite has no fallback: whatever the input lacks, the dataset loses.
    # Both axes therefore have to be supersets of the local ones.
    ensure_covers_local_dates(local_frame, incoming_frame, label)
    ensure_covers_local_stocks(local_frame, incoming_frame, label)
    report = compare_overlap(local_frame, incoming_frame, label, tolerance)
    if report.mismatches:
        LOG.warning(
            "%s; Barra 为全量重算，仍按输入覆盖", report.mismatch_message(label)
        )
        stats.barra_history_warnings += 1

    stats.barra_replaced += 1
    # Both frames run to hundreds of MB; releasing them here keeps the next
    # factor from loading on top of this one.
    del local_frame, incoming_frame
