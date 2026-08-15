"""Staging area: write everything aside first, replace the dataset only at the end.

The point is that an update either lands completely or not at all. A file that
fails halfway must not leave the dataset half new and half old — the hardest
state to diagnose, because every file looks fine on its own and only the
cross-file relations are broken.
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from data_factory.ingestion.pickle_io import dump_pickle

LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StagingCheckpoint:
    """Immutable snapshot of the staging map, used to undo one source."""

    staged: dict[Path, Path]


class StagingArea:
    """Collect the files to be written and commit them in one pass.

    The staging directory has to live on the same filesystem as the dataset for
    ``os.replace`` to be atomic; across filesystems it degrades into copy plus
    delete, which leaves half a file behind when it fails.
    """

    def __init__(self, staging_root: Path, data_root: Path) -> None:
        self._staging_root = staging_root
        self._data_root = data_root
        #: Target file -> staged file. Repeated updates keep only the last one.
        self._staged: dict[Path, Path] = {}
        self._version = 0

    def __len__(self) -> int:
        return len(self._staged)

    def source_path(self, target: Path) -> Path:
        """Which path holds the current content of ``target``.

        Already staged targets return their staged version. Multi-day increments
        depend on it: the second day has to build on the first day's result, and
        reading the original file every time would discard the earlier days.
        """
        return self._staged.get(target, target)

    def checkpoint(self) -> StagingCheckpoint:
        """Record the current state so it can be rolled back to."""
        return StagingCheckpoint(dict(self._staged))

    def rollback(self, checkpoint: StagingCheckpoint) -> None:
        """Drop every candidate staged after the checkpoint."""
        keep = set(checkpoint.staged.values())
        for staged in set(self._staged.values()) - keep:
            staged.unlink(missing_ok=True)
        self._staged = dict(checkpoint.staged)

    def stage_stream(self, target: Path, stream: BinaryIO) -> Path:
        """Stage a binary stream verbatim, for files replaced as delivered."""
        staged = self._prepare(target)
        with staged.open("wb") as destination:
            # A single Barra file runs to hundreds of MB; chunked copying keeps
            # it out of memory.
            shutil.copyfileobj(stream, destination, length=8 * 1024 * 1024)
        self._staged[target] = staged
        return staged

    def stage_object(self, target: Path, value: object) -> Path:
        """Stage an in-memory object, for merged results."""
        staged = self._prepare(target)
        dump_pickle(value, staged)
        self._staged[target] = staged
        return staged

    def discard(self, target: Path) -> None:
        """Drop a staged result that could not be produced safely."""
        staged = self._staged.pop(target, None)
        if staged is not None:
            staged.unlink(missing_ok=True)

    def commit(self) -> None:
        """Apply every staged file, restoring targets on ordinary I/O errors."""
        LOG.info("开始提交 %d 个文件", len(self._staged))
        backups = self._staging_root / ".commit-backups"
        applied: list[tuple[Path, Path | None]] = []
        try:
            for target, staged in sorted(
                self._staged.items(), key=lambda item: str(item[0])
            ):
                target.parent.mkdir(parents=True, exist_ok=True)
                backup: Path | None = None
                if target.exists():
                    backup = backups / target.relative_to(self._data_root)
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, backup)
                os.replace(staged, target)
                applied.append((target, backup))
                LOG.info("已更新 %s", target)
        except Exception as commit_error:
            rollback_errors: list[str] = []
            for target, backup in reversed(applied):
                try:
                    if backup is None:
                        target.unlink(missing_ok=True)
                    else:
                        os.replace(backup, target)
                except OSError as rollback_error:
                    rollback_errors.append(f"{target}: {rollback_error}")
            if rollback_errors:
                raise RuntimeError(
                    "提交失败且部分文件回滚失败: " + "; ".join(rollback_errors)
                ) from commit_error
            raise

    def _prepare(self, target: Path) -> Path:
        """Work out the staged path for ``target`` and create its parent.

        The staging area mirrors the dataset's directory structure, so files with
        the same name in different directories cannot collide, and every commit
        is a move within one filesystem.
        """
        # Each write gets its own version, so a candidate a checkpoint still
        # points at is never overwritten by a later one.
        self._version += 1
        staged = (
            self._staging_root
            / ".versions"
            / str(self._version)
            / target.relative_to(self._data_root)
        )
        staged.parent.mkdir(parents=True, exist_ok=True)
        return staged
