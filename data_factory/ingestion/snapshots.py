"""Validation of the full reference snapshots.

The trading calendar, the symbol table and the stock-info table are not
date-by-symbol matrices but reference data delivered in full every time. They
have no incremental semantics and can only be replaced wholesale, so all that is
left to do is check that the replacement is sane.
"""

from __future__ import annotations

import logging

import pandas as pd

from data_factory.ingestion.models import UpdateError

LOG = logging.getLogger(__name__)


def validate_snapshot(local: object, incoming: object, label: str) -> None:
    """Confirm the new snapshot can safely replace the old one.

    There is one requirement behind all the checks: reference data only grows.
    Losing codes or changing fields has to stop for a human instead of being
    written over the only copy that still has them.
    """
    if type(local) is not type(incoming):
        raise UpdateError(
            f"{label}: 类型变了——本地 {type(local).__name__}，"
            f"输入 {type(incoming).__name__}"
        )

    if isinstance(local, pd.Series):
        _validate_series(local, incoming, label)
    elif isinstance(local, pd.DataFrame):
        _validate_frame(local, incoming, label)
    else:
        raise UpdateError(f"{label}: 不支持的参考快照类型 {type(local).__name__}")

    LOG.info("%s: 全量快照结构校验通过", label)


def _validate_series(local: pd.Series, incoming: pd.Series, label: str) -> None:
    """One-dimensional value sets such as the calendar and the symbol table.

    Sets are compared, positions are not: row numbers carry no meaning in these
    tables, and one code inserted in the middle would shift everything after it,
    turning a positional comparison into nothing but false differences.
    """
    if local.isna().any() or incoming.isna().any():
        raise UpdateError(f"{label}: 参考序列里含空值")

    local_values = pd.Index(local.tolist())
    incoming_values = pd.Index(incoming.tolist())
    if local_values.has_duplicates:
        duplicates = local_values[local_values.duplicated()].unique()[:5].tolist()
        raise UpdateError(f"{label}: 本地参考序列含重复值，例如 {duplicates}")
    if incoming_values.has_duplicates:
        duplicates = incoming_values[incoming_values.duplicated()].unique()[:5].tolist()
        raise UpdateError(f"{label}: 输入参考序列含重复值，例如 {duplicates}")

    missing = local_values.difference(incoming_values)
    added = incoming_values.difference(local_values)
    if len(missing):
        raise UpdateError(f"{label}: {_shrink_reason(missing, added, '取值')}")

    LOG.info(
        "%s: %d 条 → %d 条（新增 %d 条）", label, len(local), len(incoming), len(added)
    )


def _validate_frame(local: pd.DataFrame, incoming: pd.DataFrame, label: str) -> None:
    """Information tables with named fields, such as the stock-info table."""
    if list(local.columns) != list(incoming.columns):
        raise UpdateError(
            f"{label}: 字段变了——本地={list(local.columns)}，"
            f"输入={list(incoming.columns)}"
        )

    # The stock-info table keys on stkcode; other snapshot frames fall back to
    # their index.
    if "stkcode" in incoming.columns:
        local_keys = pd.Index(local["stkcode"])
        incoming_keys = pd.Index(incoming["stkcode"])
        key_name = "stkcode"
    else:
        local_keys = local.index
        incoming_keys = incoming.index
        key_name = "索引"

    if local_keys.isna().any() or incoming_keys.isna().any():
        raise UpdateError(f"{label}: {key_name}含空值")
    if local_keys.has_duplicates:
        duplicates = local_keys[local_keys.duplicated()].unique()[:5].tolist()
        raise UpdateError(f"{label}: 本地含重复{key_name}，例如 {duplicates}")
    if incoming_keys.has_duplicates:
        duplicates = incoming_keys[incoming_keys.duplicated()].unique()[:5].tolist()
        raise UpdateError(f"{label}: 输入含重复{key_name}，例如 {duplicates}")

    missing = local_keys.difference(incoming_keys)
    added = incoming_keys.difference(local_keys)
    if len(missing):
        raise UpdateError(f"{label}: {_shrink_reason(missing, added, key_name)}")

    LOG.info(
        "%s: %d 行 → %d 行（新增 %d 行）", label, len(local), len(incoming), len(added)
    )


def _shrink_reason(missing: pd.Index, added: pd.Index, unit: str) -> str:
    """Explain why the input was rejected.

    When the input is a strict subset of the local copy, the usual cause is not
    that the vendor lost data but that this delivery has already been applied (or
    that an older one was picked). Saying so first keeps the investigation off
    the wrong track.
    """
    detail = f"缺少 {len(missing)} 个本地已有{unit}，例如 {missing[:5].tolist()}"
    if len(added) == 0:
        return f"全量输入完全落后于本地（{detail}），这批交付可能已经应用过"
    return f"全量输入丢失了本地已有{unit}（{detail}），同时新增了 {len(added)} 个"
