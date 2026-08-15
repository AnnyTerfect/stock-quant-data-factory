"""File-name index of the local dataset.

A delivery organizes its files differently from the dataset
(``FundData/fund_asset.pkl`` against ``market/bars/1d/...``), so the only stable
correspondence between the two is the file name. Matching therefore happens on
names, and this module turns the dataset into "name -> absolute path".
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

from data_factory.core.layout import is_pickle
from data_factory.ingestion.errors import UpdateError

LOG = logging.getLogger(__name__)


def build_catalog(root: Path, skip: Iterable[Path] = ()) -> dict[str, Path]:
    """Index ``root`` recursively as file name to path.

    Duplicate names are a hard error: matching by name presupposes the name is
    unique, and guessing which copy an increment belongs to would write data to
    the wrong place.

    Args:
        root: Directory to index.
        skip: Directories to leave out, for parts of the dataset this flow does
            not update. Which ones those are is the caller's decision.
    """
    excluded = tuple(skip)
    found: dict[str, list[Path]] = {}
    for path in root.rglob("*"):
        if not path.is_file() or not is_pickle(path):
            continue
        if any(path.is_relative_to(directory) for directory in excluded):
            continue
        found.setdefault(path.name, []).append(path)

    collisions = {name: paths for name, paths in found.items() if len(paths) > 1}
    if collisions:
        details = "; ".join(
            f"{name}: {', '.join(str(path) for path in paths)}"
            for name, paths in collisions.items()
        )
        raise UpdateError(f"{root} 下存在同名文件，无法按文件名安全匹配: {details}")

    LOG.info("已索引 %s 下的 %d 个数据文件", root, len(found))
    return {name: paths[0] for name, paths in found.items()}
