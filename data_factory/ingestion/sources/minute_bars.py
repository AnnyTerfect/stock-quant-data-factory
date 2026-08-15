"""Minute bars: whole trading days, one delivered file at a time.

Delivery shape: ``Kline_incre.zip`` holds a handful of flat
``kline_day_YYYYMMDD.pkl`` members, each one trading day of long-format bars (one
row per stock per minute), matching the dataset's ``market/bars/1m/``.

The unit here is the day, not the cell. A minute file is a long table with no
date axis to merge on, so a day the dataset does not have is written exactly as
delivered, and a day it already has is compared instead of overwritten. As with
the factor increments, a delivered day that disagrees with the stored one is an
``ERROR``: an increment is supposed to repeat history verbatim, and overwriting
would bury the question of which of the two copies is wrong.

Matching goes by the date in the file name, not through the dataset's file-name
catalog every other source uses: the point of this delivery is to bring days the
dataset has never seen, and a catalog of existing names cannot hold those.
"""

from __future__ import annotations

import logging
import pickle
import zipfile
from pathlib import Path

import pandas as pd

from data_factory.core.conventions import MINUTE_FIELDS, format_date
from data_factory.core.layout import minute_file_date, minute_file_name, minute_files
from data_factory.ingestion.archives import (
    iter_pickle_members,
    member_basename,
    validate_archive_limits,
)
from data_factory.ingestion.date_consistency import (
    check_against_window,
    normalize_dates,
    reference_window,
)
from data_factory.ingestion.matrix import load_matrix
from data_factory.ingestion.models import UpdateError, UpdateStats
from data_factory.ingestion.storage import StagingArea

LOG = logging.getLogger(__name__)

#: What the minute bars are called in log lines and in the day-sequence check.
LABEL = "1m bars"

#: Fields every minute file has to carry. Exactly what the conversion reads, so
#: a day accepted here cannot fail there for a field that was never delivered.
_REQUIRED_COLUMNS = ("code", "date", "time", *MINUTE_FIELDS)

#: Failures that concern one trading day and must not take the others with it.
#: TypeError and ValueError come from pandas when a delivered table is shaped
#: differently than a minute file, which is equally a single day's problem.
_RECOVERABLE_DAY = (
    UpdateError,
    pickle.UnpicklingError,
    EOFError,
    TypeError,
    ValueError,
)


def update(
    archive_path: Path,
    minute_dir: Path,
    catalog: dict[str, Path],
    staging: StagingArea,
    stats: UpdateStats,
) -> None:
    """Stage every delivered trading day the dataset does not have yet.

    Args:
        archive_path: Path of ``Kline_incre.zip``.
        minute_dir: The dataset's minute-bar directory.
        catalog: The dataset's "file name -> path" index, read only for the
            trading calendar the resulting day sequence is checked against.
        staging: Staging area receiving every new day.
        stats: Running tally.
    """
    if not archive_path.is_file():
        raise UpdateError(f"找不到分钟行情压缩包: {archive_path}")
    if not minute_dir.is_dir():
        raise UpdateError(f"找不到本地分钟行情目录: {minute_dir}")

    added: list[int] = []
    with zipfile.ZipFile(archive_path) as archive:
        validate_archive_limits(archive, archive_path.name)
        days = _delivered_days(archive, archive_path.name)
        LOG.info(
            "分钟行情: 开始处理 %s（共 %d 个交易日）", archive_path.name, len(days)
        )

        for date, member in days:
            target = minute_dir / minute_file_name(date)
            try:
                if _apply_day(archive, member, date, target, staging, stats):
                    added.append(date)
            except _RECOVERABLE_DAY as error:
                LOG.error(
                    "分钟行情/%s: 处理失败: %s: %s",
                    minute_file_name(date),
                    type(error).__name__,
                    error,
                )
                staging.discard(target)

    _check_day_sequence(minute_dir, added, catalog, staging)


def _delivered_days(
    archive: zipfile.ZipFile, archive_name: str
) -> list[tuple[int, zipfile.ZipInfo]]:
    """Read the archive's members as ``(trading day, member)``, oldest first.

    Every pickle in this archive is supposed to be one trading day, so a name
    that does not spell one is an error rather than something to skip: the
    delivery has changed shape, and guessing which day such a file belongs to is
    exactly what must not happen.
    """
    days: dict[int, zipfile.ZipInfo] = {}
    duplicates: set[int] = set()
    for member in iter_pickle_members(archive):
        name = member_basename(member.filename)
        date = minute_file_date(Path(name))
        if date is None:
            raise UpdateError(
                f"{archive_name} 里有不符合分钟文件命名规则的成员: {name}"
            )
        if date in days:
            duplicates.add(date)
        days[date] = member

    if duplicates:
        raise UpdateError(f"{archive_name} 里出现重复的交易日: {sorted(duplicates)}")
    if not days:
        raise UpdateError(f"{archive_name} 里没有任何分钟行情文件")
    return sorted(days.items())


def _apply_day(
    archive: zipfile.ZipFile,
    member: zipfile.ZipInfo,
    date: int,
    target: Path,
    staging: StagingArea,
    stats: UpdateStats,
) -> bool:
    """Stage or verify one trading day; return whether it was staged."""
    label = f"分钟行情/{minute_file_name(date)}"
    if target.exists():
        _verify_existing_day(archive, member, target, label, stats)
        return False

    # Staged verbatim, the way Barra is: the delivered bytes are what the
    # dataset will hold anyway, and at ~70 MB a day, re-serializing a frame that
    # only had to be checked would buy nothing.
    with archive.open(member) as stream:
        staged = staging.stage_stream(target, stream)
    _validate_day(load_matrix(staged, label), date, label)

    stats.minute_days_added += 1
    LOG.info("%s: 新增交易日", label)
    return True


def _validate_day(frame: pd.DataFrame, date: int, label: str) -> None:
    """Confirm a new day is one trading day of complete, unambiguous bars."""
    _ensure_columns(frame, label)
    if frame.empty:
        raise UpdateError(f"{label}: 没有任何行情数据")

    dates = pd.unique(frame["date"])
    if len(dates) != 1 or int(dates[0]) != date:
        raise UpdateError(
            f"{label}: 文件名日期与数据日期不符，数据里的日期为 {dates[:5].tolist()}"
        )
    if frame.duplicated(["code", "time"]).any():
        duplicated = frame.loc[frame.duplicated(["code", "time"]), ["code", "time"]]
        raise UpdateError(
            f"{label}: 存在重复的 code/time，例如 "
            f"{duplicated.head(5).to_numpy().tolist()}"
        )


def _verify_existing_day(
    archive: zipfile.ZipFile,
    member: zipfile.ZipInfo,
    target: Path,
    label: str,
    stats: UpdateStats,
) -> None:
    """Compare a day the dataset already holds against the delivered one.

    Nothing is staged either way: the local file stays as it is, and a
    difference is reported so that a human decides which copy is wrong. Both
    frames are read at once, which is why this never runs for more than one day
    at a time.
    """
    local = load_matrix(target, f"{label}（本地）")
    with archive.open(member) as stream:
        incoming = load_matrix(stream, f"{label}（输入）")

    difference = _describe_difference(local, incoming, label)
    del local, incoming
    if difference is not None:
        LOG.error("%s: 已有交易日与输入不一致——%s", label, difference)
        return

    stats.minute_days_verified += 1
    LOG.info("%s: 本地已有且与输入一致，跳过", label)


def _describe_difference(
    local: pd.DataFrame, incoming: pd.DataFrame, label: str
) -> str | None:
    """Say how two copies of one trading day differ, or ``None`` if they do not.

    Row order carries no meaning in a long table, so both sides are put in the
    same order first; comparing as delivered would report a reordered file as
    wholly different and hide the one field that actually changed.
    """
    _ensure_columns(local, f"{label}（本地）")
    _ensure_columns(incoming, f"{label}（输入）")

    if list(local.columns) != list(incoming.columns):
        return f"字段不同：本地 {list(local.columns)}，输入 {list(incoming.columns)}"
    if len(local) != len(incoming):
        return f"行数不同：本地 {len(local)} 行，输入 {len(incoming)} 行"

    left = local.sort_values(["code", "time"], kind="stable", ignore_index=True)
    right = incoming.sort_values(["code", "time"], kind="stable", ignore_index=True)
    unequal = [
        column for column in left.columns if not left[column].equals(right[column])
    ]
    if unequal:
        return f"{len(unequal)} 个字段的取值不同，例如 {unequal[:5]}"
    return None


def _ensure_columns(frame: pd.DataFrame, label: str) -> None:
    """Confirm a minute table carries every field the dataset relies on."""
    missing = [column for column in _REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise UpdateError(f"{label}: 缺少字段 {missing}")


def _check_day_sequence(
    minute_dir: Path,
    added: list[int],
    catalog: dict[str, Path],
    staging: StagingArea,
) -> None:
    """Check the trading days the dataset will hold against the updated calendar.

    Minute bars are a directory of days rather than a matrix with a date axis, so
    the global date-consistency pass cannot see them. The days it would look at
    are all in the file names, though, which makes the same check — no hole, no
    non-trading day, no stale tail — cost one directory listing.
    """
    local = {minute_file_date(path) for path in minute_files(minute_dir)}
    days = sorted(local | set(added))
    if not days:
        LOG.warning("%s: 更新后仍然没有任何交易日文件，跳过日期连续性校验", LABEL)
        return

    try:
        dates = normalize_dates(days, LABEL)
    except UpdateError as error:
        LOG.error("%s", error)
        return

    problem = check_against_window(dates, reference_window(catalog, staging), LABEL)
    if problem:
        LOG.error("%s", problem)
        return
    LOG.info(
        "%s: 更新后共 %d 个交易日，末日期 %s，与交易日历一致",
        LABEL,
        len(dates),
        format_date(dates[-1]),
    )
