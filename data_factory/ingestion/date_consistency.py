"""Trading-day consistency of every date matrix after the update.

Using the updated calendar as the baseline, each date matrix is checked over the
most recent trading days. What matters is telling three deviations apart,
because they are not equally serious:

* **Hole** — a trading day the calendar has and the file skips inside the range
  it already covers. Data really is missing, so it is an ``ERROR``.
* **Extra date** — a date the file has and the calendar does not. The date axis
  is wrong, so it is an ``ERROR``.
* **Tail lag** — the file's last date precedes the calendar's. Some upstream
  files (universe, for one) are always published a beat late, which is the normal
  rhythm: a ``WARNING`` naming the lag, escalating to ``ERROR`` only beyond
  :data:`MAX_DATE_LAG_DAYS`.

An earlier version conflated the three by taking the last N dates of each axis
and comparing them pairwise. One day of lag shifted the two windows apart, so old
dates outside the window were reported as "missing" and "extra" — pointing at
years that had nothing to do with the update.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from data_factory.core.conventions import (
    DateAxisError,
    ensure_sorted_dates,
    ensure_unique_dates,
    format_date,
    format_dates,
    to_datetime_index,
)
from data_factory.ingestion.models import (
    DATE_CONSISTENCY_DAYS,
    DATE_REFERENCE_FILE,
    MAX_DATE_LAG_DAYS,
    NON_DATE_FILES,
    UpdateError,
)
from data_factory.ingestion.storage import StagingArea, load_pickle

LOG = logging.getLogger(__name__)


def validate_recent_dates(catalog: dict[str, Path], staging: StagingArea) -> None:
    """Compare every date matrix over the last ``DATE_CONSISTENCY_DAYS`` trading days.

    Files updated in this run are read from the staging area and the rest from
    the dataset, so what the check sees is exactly the dataset a commit produces.
    """
    window = _reference_window(catalog, staging)

    checked = 0
    problems: list[str] = []
    for name, target in sorted(catalog.items()):
        if name == DATE_REFERENCE_FILE or name in NON_DATE_FILES:
            continue

        value = load_pickle(staging.source_path(target))
        if not isinstance(value, pd.DataFrame):
            problems.append(f"{name}: 期望 DataFrame，实际是 {type(value).__name__}")
            continue

        try:
            dates = _normalize_dates(value.index, name)
        except UpdateError as error:
            problems.append(str(error))
            continue
        if len(dates) == 0:
            problems.append(f"{name}: 日期轴为空")
            continue

        checked += 1
        problem = _check_against_window(dates, window, name)
        if problem:
            problems.append(problem)

    if problems:
        details = "; ".join(problems)
        raise UpdateError(
            f"更新后最近 {DATE_CONSISTENCY_DAYS} 日日期不一致（"
            f"{len(problems)} 个文件）: {details}"
        )

    LOG.info(
        "全局日期校验通过: %d 个矩阵最近 %d 日与 %s 一致",
        checked,
        DATE_CONSISTENCY_DAYS,
        DATE_REFERENCE_FILE,
    )


def _reference_window(
    catalog: dict[str, Path], staging: StagingArea
) -> pd.DatetimeIndex:
    """The most recent N trading days of the updated calendar, as the baseline."""
    reference_target = catalog.get(DATE_REFERENCE_FILE)
    if reference_target is None:
        raise UpdateError(f"数据目录缺少日期基准文件 {DATE_REFERENCE_FILE}")

    reference = load_pickle(staging.source_path(reference_target))
    if not isinstance(reference, pd.Series):
        raise UpdateError(
            f"{DATE_REFERENCE_FILE}: 期望 Series，实际是 {type(reference).__name__}"
        )
    reference_dates = _normalize_dates(reference.tolist(), DATE_REFERENCE_FILE)
    if len(reference_dates) < DATE_CONSISTENCY_DAYS:
        raise UpdateError(
            f"{DATE_REFERENCE_FILE}: 仅 {len(reference_dates)} 个日期，"
            f"不足以校验最近 {DATE_CONSISTENCY_DAYS} 日"
        )
    return reference_dates[-DATE_CONSISTENCY_DAYS:]


def _check_against_window(
    dates: pd.DatetimeIndex, window: pd.DatetimeIndex, name: str
) -> str | None:
    """Check one file's date axis; a pure tail lag only warns and returns None.

    The comparison runs over the intersection of "what the file covers" and the
    baseline window, so a young factor is not blamed for the history it never
    had, and a tail lag does not spill over into the start of the window.
    """
    # The part of the file that falls inside the baseline window. History outside
    # it takes no part in this round.
    inside = dates[(dates >= window[0]) & (dates <= window[-1])]
    last = dates[-1]

    # What the file ought to cover: the window from its own start up to its own
    # last date. Truncating at the last date separates "not published yet" from
    # "skipped a day in the middle".
    start = inside[0] if len(inside) else last
    expected = window[(window >= start) & (window <= last)]

    missing = expected.difference(inside)
    extra = inside.difference(window)
    if len(missing) or len(extra):
        return (
            f"{name}: 区间 {format_date(start)}~{format_date(last)} 内"
            f"缺失 {len(missing)} 个交易日（例 {format_dates(missing)}）、"
            f"多出 {len(extra)} 个非交易日（例 {format_dates(extra)}）"
        )

    # Getting here means the covered part matches the calendar exactly, so the
    # only possible deviation left is the file being short at the end.
    lag = len(window[window > last])
    if lag > MAX_DATE_LAG_DAYS:
        return (
            f"{name}: 末日期 {format_date(last)} "
            f"比日历末日期 {format_date(window[-1])} "
            f"落后 {lag} 个交易日，超过允许的 {MAX_DATE_LAG_DAYS} 个"
        )
    if lag:
        LOG.warning(
            "%s: 末日期 %s 比日历末日期 %s 落后 %d 个交易日，"
            "已覆盖的区间与日历一致，请确认是否符合该文件的发布节奏",
            name,
            format_date(last),
            format_date(window[-1]),
            lag,
        )
    return None


def _normalize_dates(values: object, label: str) -> pd.DatetimeIndex:
    """Parse a date axis, requiring it to be unique and ascending.

    A malformed axis aborts the whole update here, so every ``DateAxisError``
    becomes an :class:`UpdateError` naming the file it came from.
    """
    try:
        dates = to_datetime_index(values)
        ensure_unique_dates(dates)
        ensure_sorted_dates(dates)
    except DateAxisError as error:
        raise UpdateError(f"{label}: {error}") from error
    return dates
