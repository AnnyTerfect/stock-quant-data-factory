"""Comparison and merging of date-by-stock matrices.

Nearly every file in the dataset has the same shape: rows are trading days
(``20260803``), columns are symbols (``000001.SZ``). Two primitives cover them:

* :func:`compare_overlap` — compares and reports, without deciding anything;
* :func:`merge` — merges, without re-checking.

Whether a difference deserves an error or a warning is each source's own policy
(Barra warns, factor increments fail), so that call stays with the caller and
this module stays pure mechanism.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import numpy as np
import pandas as pd

from data_factory.ingestion.models import (
    COLUMN_CHUNK_SIZE,
    MISMATCH_EXAMPLE_LIMIT,
    Tolerance,
    UpdateError,
)
from data_factory.ingestion.storage import load_pickle

LOG = logging.getLogger(__name__)


def load_matrix(source: Path | BinaryIO, label: str) -> pd.DataFrame:
    """Read a matrix pickle and confirm it really is a DataFrame."""
    value = load_pickle(source)
    if not isinstance(value, pd.DataFrame):
        raise UpdateError(f"{label}: 期望 DataFrame，实际是 {type(value).__name__}")
    return value


# ---------------------------------------------------------------------------
# Structural checks
# ---------------------------------------------------------------------------


def ensure_unique_axes(frame: pd.DataFrame, label: str) -> None:
    """Confirm neither dates nor symbols repeat.

    Duplicated labels make the later ``.loc`` alignment silently produce a
    cartesian product, which invalidates both comparison and merge — so this is
    a hard precondition rather than a warning.
    """
    if not frame.index.is_unique:
        duplicates = frame.index[frame.index.duplicated()].unique()[:5].tolist()
        raise UpdateError(f"{label}: 日期索引有重复值，例如 {duplicates}")
    if not frame.columns.is_unique:
        duplicates = frame.columns[frame.columns.duplicated()].unique()[:5].tolist()
        raise UpdateError(f"{label}: 股票列有重复值，例如 {duplicates}")


def has_date_axis(index: pd.Index) -> bool:
    """Whether the row index looks like a YYYYMMDD trading-day axis.

    Deciding "date matrix or reference table" from a hand-kept list of file names
    means every table the list forgot (``ind_code_CI.pkl``, indexed 0..570) gets
    merged as a date matrix: intersected and reordered on row numbers, quietly
    corrupted. Judging by the shape of the index needs no list to be updated.
    """
    if isinstance(index, pd.DatetimeIndex):
        return True
    if len(index) == 0 or index.dtype.kind not in "iu":
        return False
    # The plausible range of 8-digit YYYYMMDD; row numbers all fall outside it.
    return bool(index.min() >= 19000101 and index.max() <= 21001231)


def ensure_covers_local_dates(
    local: pd.DataFrame, incoming: pd.DataFrame, label: str
) -> None:
    """Confirm a full delivery drops none of the dates already held locally.

    Only meaningful for overwriting sources: after the overwrite the dataset
    holds exactly the input's dates, so a missing date deletes history.
    """
    missing = local.index[~local.index.isin(incoming.index)]
    if len(missing):
        raise UpdateError(
            f"{label}: 全量输入缺少 {len(missing)} 个本地已有日期，"
            f"例如 {missing[:5].tolist()}"
        )


def ensure_covers_local_stocks(
    local: pd.DataFrame, incoming: pd.DataFrame, label: str
) -> None:
    """Confirm a full delivery drops none of the symbols already held locally.

    The counterpart of :func:`ensure_covers_local_dates`, and equally limited to
    overwriting sources. Merging sources must not check this: an increment's
    universe is naturally narrower than the local one (no delisted names), and a
    merge only writes the submatrix the input covers, leaving local-only symbols
    untouched. An overwrite replaces everything, so a missing symbol there erases
    its entire history.
    """
    missing = local.columns[~local.columns.isin(incoming.columns)]
    if len(missing):
        raise UpdateError(
            f"{label}: 全量输入缺少 {len(missing)} 只本地已有股票，"
            f"例如 {missing[:5].tolist()}"
        )


# ---------------------------------------------------------------------------
# Overlapping history
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OverlapReport:
    """The outcome of comparing one overlapping region."""

    dates: int
    """Dates held by both the local file and the input."""

    stocks: int
    """Symbols held by both."""

    mismatches: int
    """Cells whose values disagree inside the overlap."""

    examples: tuple[str, ...] = ()
    """Up to ``MISMATCH_EXAMPLE_LIMIT`` samples, enough to locate the problem."""

    max_deviation: float = 0.0
    """Largest relative deviation in the overlap; meaningful for numeric data."""

    def mismatch_message(self, label: str) -> str:
        """Render the differences as one line fit for a log or an exception.

        The largest deviation is carried along to make the warning triageable:
        Barra re-estimates its whole history every delivery, so last-digit noise
        produces tens of thousands of "differences", and a count alone cannot
        separate float noise from a genuinely wrong number.
        """
        share = self.mismatches / max(self.dates * self.stocks, 1)
        return (
            f"{label}: 历史对不上——{self.dates} 个重叠日期 × {self.stocks} 只共同股票中"
            f"发现 {self.mismatches} 处差异（占比 {share:.2%}，"
            f"最大相对偏差 {self.max_deviation:.3e}）。样例: {'; '.join(self.examples)}"
        )


def compare_overlap(
    local: pd.DataFrame,
    incoming: pd.DataFrame,
    label: str,
    tolerance: Tolerance,
) -> OverlapReport:
    """Compare both frames on their common dates and common symbols.

    Explicit alignment is the point: an input's universe routinely differs from
    the local one (listings, delistings), so comparing by position would be
    wrong throughout. Each side is intersected first, then compared.
    """
    ensure_unique_axes(local, f"{label}（本地）")
    ensure_unique_axes(incoming, f"{label}（输入）")

    common_dates = local.index[local.index.isin(incoming.index)]
    common_stocks = local.columns[local.columns.isin(incoming.columns)]

    if len(common_dates) == 0:
        # No overlap means this file went unchecked. That is normal for a first
        # delivery or after a long gap, and abnormal when the local date axis has
        # a different type or convention than the input — which would silently
        # concatenate two unrelated histories. The two are indistinguishable from
        # here, so the file passes but the run carries a warning for a human.
        LOG.warning(
            "%s: 与本地没有任何重叠日期，本次跳过历史比较，请确认是否符合预期", label
        )
        return OverlapReport(0, len(common_stocks), 0)
    if len(common_stocks) == 0:
        raise UpdateError(f"{label}: 对齐后没有任何共同股票，无法校验历史")

    mismatches = 0
    max_deviation = 0.0
    examples: list[str] = []
    for columns in _column_chunks(common_stocks):
        left = local.loc[common_dates, columns]
        right = incoming.loc[common_dates, columns]
        unequal = _unequal_mask(left, right, tolerance)

        count = int(np.count_nonzero(unequal))
        mismatches += count
        if count:
            max_deviation = max(
                max_deviation, _max_relative_deviation(left, right, unequal)
            )
        if count and len(examples) < MISMATCH_EXAMPLE_LIMIT:
            examples.extend(
                _describe_mismatches(
                    common_dates,
                    columns,
                    unequal,
                    left.to_numpy(),
                    right.to_numpy(),
                    limit=MISMATCH_EXAMPLE_LIMIT - len(examples),
                )
            )

    LOG.info(
        "%s: 重叠 %d 日 × %d 股，差异 %d 处",
        label,
        len(common_dates),
        len(common_stocks),
        mismatches,
    )
    return OverlapReport(
        len(common_dates),
        len(common_stocks),
        mismatches,
        tuple(examples),
        max_deviation,
    )


def _max_relative_deviation(
    left: pd.DataFrame, right: pd.DataFrame, unequal: np.ndarray
) -> float:
    """Largest relative deviation among the differing cells; 0 for non-numerics.

    The denominator is the larger absolute value of the two, so values near zero
    do not inflate the ratio; a zero against a non-zero yields 1, which lands
    firmly on the "clearly different" side.
    """
    if not (_is_all_numeric(left) and _is_all_numeric(right)):
        return 0.0

    left_values = left.to_numpy(dtype=np.float64)[unequal]
    right_values = right.to_numpy(dtype=np.float64)[unequal]
    scale = np.maximum(np.abs(left_values), np.abs(right_values))
    with np.errstate(invalid="ignore", divide="ignore"):
        relative = np.where(scale > 0, np.abs(left_values - right_values) / scale, 0.0)
    # NaN against a value counts as a difference but has no deviation to report.
    finite = relative[np.isfinite(relative)]
    return float(finite.max()) if finite.size else 0.0


def _column_chunks(columns: pd.Index) -> Iterator[pd.Index]:
    """Slice the symbol columns so the overlap is never materialized at once."""
    for start in range(0, len(columns), COLUMN_CHUNK_SIZE):
        yield columns[start : start + COLUMN_CHUNK_SIZE]


def _unequal_mask(
    left: pd.DataFrame, right: pd.DataFrame, tolerance: Tolerance
) -> np.ndarray:
    """Boolean matrix, True where the two sides disagree.

    Numeric on both sides compares within tolerance, because recomputed floats
    wobble in the last digits and that is not a difference; anything else (status
    strings, say) falls back to exact comparison. Both paths treat NaN on both
    sides as equal.
    """
    left_values = left.to_numpy()
    right_values = right.to_numpy()

    if _is_all_numeric(left) and _is_all_numeric(right):
        equal = np.isclose(
            left_values,
            right_values,
            rtol=tolerance.rtol,
            atol=tolerance.atol,
            equal_nan=True,
        )
    else:
        # Comparing pandas nullable string/boolean columns yields pd.NA, and
        # converting that to numpy before the boolean operations raises
        # "boolean value of NA is ambiguous". Unknown comparisons are taken as
        # unequal first, then cells missing on both sides are restored as equal.
        equal = left.eq(right).fillna(False).to_numpy(dtype=bool, copy=True)
        equal |= pd.isna(left_values) & pd.isna(right_values)

    return ~equal


def _is_all_numeric(frame: pd.DataFrame) -> bool:
    return all(pd.api.types.is_numeric_dtype(dtype) for dtype in frame.dtypes)


def _describe_mismatches(
    dates: pd.Index,
    stocks: pd.Index,
    unequal: np.ndarray,
    left_values: np.ndarray,
    right_values: np.ndarray,
    limit: int,
) -> list[str]:
    """Render the first ``limit`` differing cells as date / symbol / both values."""
    described = []
    for row, column in np.argwhere(unequal)[:limit]:
        described.append(
            f"date={dates[row]!r}, stock={stocks[column]!r}, "
            f"local={left_values[row, column]!r}, "
            f"incoming={right_values[row, column]!r}"
        )
    return described


# ---------------------------------------------------------------------------
# Merging
# ---------------------------------------------------------------------------


def merge(local: pd.DataFrame, incoming: pd.DataFrame, label: str) -> pd.DataFrame:
    """Merge an increment into the local matrix and return the new matrix.

    Callers are expected to have confirmed the overlap with
    :func:`compare_overlap`; this function does not check it again.
    """
    all_dates = _ordered_union(local.index, incoming.index)
    all_stocks = _ordered_union(local.columns, incoming.columns)

    merged = _place(local, incoming, all_dates, all_stocks)
    merged = _sorted_by_date(merged)
    # reindex drops the axis names; restoring them keeps the file's structure
    # identical to what it was before the update.
    merged.index.name = local.index.name or incoming.index.name
    merged.columns.name = local.columns.name or incoming.columns.name

    LOG.info(
        "%s: 合并完成，新增 %d 个日期、%d 只股票，结果 shape=%s",
        label,
        len(all_dates) - len(local.index),
        len(all_stocks) - len(local.columns),
        merged.shape,
    )
    return merged


def _place(
    local: pd.DataFrame,
    incoming: pd.DataFrame,
    all_dates: pd.Index,
    all_stocks: pd.Index,
) -> pd.DataFrame:
    """Lay both frames onto the union grid, the input winning.

    Only the date-by-symbol block the input actually covers is overwritten: an
    increment's universe is usually narrower than the local one (no delisted
    names), and writing whole rows would blank local-only symbols on those dates.
    """
    dtype = _uniform_dtype(local, incoming, all_dates, all_stocks)
    if dtype is not None:
        return _place_numpy(local, incoming, all_dates, all_stocks, dtype)
    return _place_pandas(local, incoming, all_dates, all_stocks)


def _uniform_dtype(
    local: pd.DataFrame,
    incoming: pd.DataFrame,
    all_dates: pd.Index,
    all_stocks: pd.Index,
) -> np.dtype | None:
    """The merged numpy dtype when both sides are single-dtype numerics, else None.

    Most factor matrices hold one dtype throughout (bars float64, industry and
    status float16, Barra float32), and those can go through numpy in one block —
    an order of magnitude faster than assigning column by column. Frames with
    mixed column dtypes (``univ_ex_ss`` carries int64 next to float64) go to
    pandas instead, so that speed never costs untouched columns their type.
    """
    local_dtypes = set(local.dtypes)
    incoming_dtypes = set(incoming.dtypes)
    if len(local_dtypes) > 1 or len(incoming_dtypes) > 1:
        return None

    dtypes = local_dtypes | incoming_dtypes
    if not all(
        isinstance(dtype, np.dtype) and dtype.kind in "iufc" for dtype in dtypes
    ):
        # Pandas extension types (nullable int, string, …) have no numpy
        # equivalent semantics, so they are left alone.
        return None

    dtype = np.result_type(*dtypes)
    if dtype.kind in "iu" and _has_gaps(local, incoming, all_dates, all_stocks):
        # The union holds cells neither side covers, so the result must be able
        # to express emptiness. Promoting to float64 matches what a pandas
        # reindex does when it introduces NaN.
        dtype = np.promote_types(dtype, np.float64)
    return dtype


def _has_gaps(
    local: pd.DataFrame,
    incoming: pd.DataFrame,
    all_dates: pd.Index,
    all_stocks: pd.Index,
) -> bool:
    """Whether the union grid holds cells neither input covers.

    Both inputs are rectangular blocks on that grid, so the covered area follows
    from arithmetic — the grid never has to be laid out.
    """
    common_dates = int(local.index.isin(incoming.index).sum())
    common_stocks = int(local.columns.isin(incoming.columns).sum())
    covered = (
        local.shape[0] * local.shape[1]
        + incoming.shape[0] * incoming.shape[1]
        - common_dates * common_stocks
    )
    return covered < len(all_dates) * len(all_stocks)


def _place_numpy(
    local: pd.DataFrame,
    incoming: pd.DataFrame,
    all_dates: pd.Index,
    all_stocks: pd.Index,
    dtype: np.dtype,
) -> pd.DataFrame:
    """Positional assignment in one numpy block."""
    values = np.full(
        (len(all_dates), len(all_stocks)),
        np.nan if dtype.kind in "fc" else 0,
        dtype=dtype,
    )
    # Order matters: the input is written second and therefore wins.
    for frame in (local, incoming):
        rows = all_dates.get_indexer(frame.index)
        columns = all_stocks.get_indexer(frame.columns)
        values[np.ix_(rows, columns)] = frame.to_numpy(dtype=dtype)
    return pd.DataFrame(values, index=all_dates, columns=all_stocks)


def _place_pandas(
    local: pd.DataFrame,
    incoming: pd.DataFrame,
    all_dates: pd.Index,
    all_stocks: pd.Index,
) -> pd.DataFrame:
    """General path for mixed column dtypes, preserving each column's own type."""
    merged = local.reindex(index=all_dates, columns=all_stocks)
    _widen_for_incoming(merged, incoming)
    merged.loc[incoming.index, incoming.columns] = incoming.to_numpy()
    return merged


def _widen_for_incoming(merged: pd.DataFrame, incoming: pd.DataFrame) -> None:
    """Promote the columns about to be written to the common dtype.

    A pandas 3.0 ``.loc`` assignment no longer widens dtypes implicitly: writing
    float32 into a float16 column raises TypeError instead of silently
    truncating. The day an upstream raises its precision, a whole update would
    exit with a traceback, so the columns are promoted up front.
    """
    current = merged.dtypes
    groups: dict[np.dtype, list] = {}
    for column, incoming_dtype in incoming.dtypes.items():
        existing = current[column]
        try:
            promoted = np.promote_types(existing, incoming_dtype)
        except TypeError:
            # Non-numeric types have no common dtype; let the assignment report it.
            continue
        if promoted != existing:
            groups.setdefault(promoted, []).append(column)

    for dtype, columns in groups.items():
        merged[columns] = merged[columns].astype(dtype)


def _ordered_union(base: pd.Index, extra: pd.Index) -> pd.Index:
    """``base`` first, then whatever ``extra`` adds, in its own order.

    Better than ``Index.union`` here because it never reorders the existing
    entries: column order is an implicit contract for anything downstream that
    reads by position, and one update should not shuffle it.
    """
    return base.append(extra[~extra.isin(base)])


def _sorted_by_date(frame: pd.DataFrame) -> pd.DataFrame:
    """Sort by date ascending; keep the order when the index cannot be sorted."""
    try:
        return frame.sort_index()
    except (TypeError, ValueError):
        LOG.warning("索引类型无法排序，保留追加顺序")
        return frame
