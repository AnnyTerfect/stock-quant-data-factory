"""Traversal of the delivered zip archives.

A delivery nests two levels: the outer archive, and — for the factor database —
one inner archive per day. This module only knows how to hand out the pickle
members inside; every business check lives elsewhere.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path, PurePosixPath

from data_factory.core.conventions import DATE_FORMAT
from data_factory.core.layout import is_pickle
from data_factory.ingestion.conventions import (
    MAX_ARCHIVE_MEMBER_BYTES,
    MAX_ARCHIVE_MEMBERS,
    MAX_ARCHIVE_TOTAL_BYTES,
    MAX_COMPRESSION_RATIO,
    MAX_INNER_ARCHIVE_BYTES,
)
from data_factory.ingestion.errors import UpdateError

LOG = logging.getLogger(__name__)

_DAILY_ARCHIVE_RE = re.compile(
    r"^factorDatabase_incre_pkl_(\d{8})\.zip$", re.IGNORECASE
)


def member_basename(member_name: str) -> str:
    """Take the file-name part of an archive member.

    Members usually carry a directory (``FundData/fund_asset.pkl``) that has no
    counterpart in the dataset, so matching strips it. This also blocks ``../``
    paths that would escape any extraction directory.
    """
    path = PurePosixPath(member_name)
    if path.name in {"", ".", ".."} or ".." in path.parts:
        raise UpdateError(f"zip 内含不安全的成员路径: {member_name!r}")
    return path.name


def iter_pickle_members(archive: zipfile.ZipFile) -> Iterator[zipfile.ZipInfo]:
    """Yield the pickle members in archive order, skipping directories."""
    for member in archive.infolist():
        if member.is_dir():
            continue
        if is_pickle(PurePosixPath(member.filename)):
            yield member


def validate_archive_limits(archive: zipfile.ZipFile, label: str) -> None:
    """Cap member count, expanded size and compression ratio before extracting."""
    members = [member for member in archive.infolist() if not member.is_dir()]
    if len(members) > MAX_ARCHIVE_MEMBERS:
        raise UpdateError(
            f"{label}: 成员数 {len(members)} 超过上限 {MAX_ARCHIVE_MEMBERS}"
        )
    total = 0
    for member in members:
        if member.file_size > MAX_ARCHIVE_MEMBER_BYTES:
            raise UpdateError(
                f"{label}/{member.filename}: 展开大小 {member.file_size} 超过上限"
            )
        total += member.file_size
        if member.file_size and (
            member.compress_size == 0
            or member.file_size / member.compress_size > MAX_COMPRESSION_RATIO
        ):
            raise UpdateError(f"{label}/{member.filename}: 压缩比异常，拒绝读取")
    if total > MAX_ARCHIVE_TOTAL_BYTES:
        raise UpdateError(f"{label}: 总展开大小 {total} 超过上限")


def iter_daily_archives(
    outer: zipfile.ZipFile,
) -> Iterator[tuple[str, zipfile.ZipFile]]:
    """Yield ``(name, open archive)`` for each daily package, oldest first.

    Increments have to be applied in date order: each day builds on the previous
    result, and out-of-order application would compare overlapping dates against
    the wrong baseline.

    Both delivery shapes are accepted: the usual one, where the outer archive
    holds one archive per day, and the degenerate one, where the outer archive
    is itself a single day and therefore acts as the only daily package.
    """
    validate_archive_limits(outer, str(outer.filename or "outer.zip"))
    candidates = [
        info
        for info in outer.infolist()
        if not info.is_dir() and info.filename.lower().endswith(".zip")
    ]

    if not candidates:
        LOG.info("外层压缩包内没有日包，按单个增量目录处理")
        yield Path(outer.filename or "increment.zip").name, outer
        return

    dated = [(info, _daily_archive_date(info.filename)) for info in candidates]
    dates = [date for _, date in dated]
    if len(set(dates)) != len(dates):
        duplicates = sorted(
            {date.strftime(DATE_FORMAT) for date in dates if dates.count(date) > 1}
        )
        raise UpdateError(f"外层压缩包含重复日包日期: {duplicates}")
    dated.sort(key=lambda item: item[1])

    LOG.info("外层压缩包内共 %d 个日包，按日期顺序处理", len(dated))
    for info, _ in dated:
        # Each daily package is read into memory before opening: ZipFile needs a
        # seekable object, and ``outer.open()`` only returns a sequential stream.
        if info.file_size > MAX_INNER_ARCHIVE_BYTES:
            raise UpdateError(f"日包 {info.filename} 大小超过内存读取上限")
        payload = io.BytesIO(outer.read(info))
        with zipfile.ZipFile(payload) as inner:
            validate_archive_limits(inner, info.filename)
            yield info.filename, inner


def _daily_archive_date(name: str) -> datetime:
    """Parse a daily package name and the YYYYMMDD date inside it, strictly."""
    basename = PurePosixPath(name).name
    match = _DAILY_ARCHIVE_RE.fullmatch(basename)
    if match is None:
        raise UpdateError(f"外层压缩包含无法识别的日包: {name!r}")
    try:
        return datetime.strptime(match.group(1), DATE_FORMAT)
    except ValueError as error:
        raise UpdateError(f"日包日期不合法: {name!r}") from error
