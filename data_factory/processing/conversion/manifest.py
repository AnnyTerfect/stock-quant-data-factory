"""What each output was converted from, so a rerun redoes only what changed.

A target that exists says nothing about whether it is current. Upstream
re-delivers corrected history under the same file names, so the useful question
is not "has this been converted before" but "has this been converted from these
exact bytes". Every conversion therefore records the SHA-256 of the source it
read, and the next run converts again exactly when that hash no longer matches.

The manifest lives in the output tree because it describes those files: a
discarded output directory takes its bookkeeping with it. Losing the file alone
costs a full reconversion and never a wrong result — a source whose hash is
unknown counts as changed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

LOG = logging.getLogger(__name__)

#: Where the record sits inside the output root.
MANIFEST_NAME = ".conversion-manifest.json"

#: Bumped only when the stored shape changes; a manifest written by an older
#: layout is dropped rather than guessed at.
_VERSION = 1


def file_digest(path: Path) -> str:
    """Hash one source file's bytes."""
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def group_digest(paths: Iterable[Path]) -> str:
    """Hash a set of sources that together produce one output.

    The minute bars are the case: six wide files are built from every daily
    pickle at once, so no single source identifies the output. Names go into the
    hash alongside the contents, which is what makes a removed or renamed
    trading day register as a change rather than as the same input.
    """
    inner = hashlib.sha256()
    for path in sorted(paths):
        inner.update(f"{path.name}\0{file_digest(path)}\n".encode())
    return inner.hexdigest()


@dataclass(slots=True)
class ConversionManifest:
    """Source hashes of everything already converted into one output root."""

    path: Path
    dry_run: bool = False
    entries: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, output_root: Path, dry_run: bool = False) -> ConversionManifest:
        """Read the output root's manifest, or start an empty one.

        An unreadable manifest is a reason to convert everything again, not a
        reason to stop: the outputs it describes may well be fine, but nothing
        here can tell which, and reconverting is the answer that cannot be wrong.
        """
        path = output_root / MANIFEST_NAME
        manifest = cls(path=path, dry_run=dry_run)
        if not path.is_file():
            return manifest
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
            if stored.get("version") != _VERSION:
                raise ValueError(f"未知的清单版本 {stored.get('version')}")
            entries = stored["entries"]
            manifest.entries = {str(key): str(value) for key, value in entries.items()}
        except (OSError, ValueError, TypeError, AttributeError, KeyError) as error:
            LOG.warning(
                "转换清单无法读取，本次将重新转换全部数据: %s: %s",
                path,
                error,
            )
            manifest.entries = {}
        return manifest

    def is_current(self, key: str, digest: str, targets: Iterable[Path]) -> bool:
        """Whether ``key`` was last converted from ``digest`` and still has output.

        Both halves matter: a matching hash with a deleted target means the
        output has to be produced again, and an existing target with no matching
        hash means it was produced from something else.
        """
        if self.entries.get(key) != digest:
            return False
        return all(target.exists() for target in targets)

    def record(self, key: str, digest: str) -> None:
        """Remember what one output was just converted from, and persist it.

        Saving per entry rather than per run is what makes an interrupted
        conversion resumable: the days that did finish keep their hashes and are
        skipped next time.
        """
        if self.entries.get(key) == digest:
            return
        self.entries[key] = digest
        self.save()

    def save(self) -> None:
        """Write the manifest atomically, so an interrupted run leaves the old one."""
        if self.dry_run:
            return
        payload = {
            "version": _VERSION,
            "entries": dict(sorted(self.entries.items())),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False),
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
