"""Logging setup shared by every command."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

LOG = logging.getLogger(__name__)

_CONSOLE_FORMAT = "%(asctime)s %(levelname)s %(message)s"
#: The file copy also carries the logger name: after the fact, "which module
#: said this" is exactly what tells apart an ingestion warning from a check one.
_FILE_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging(
    log_dir: Path | None,
    name: str,
    *,
    verbose: bool = False,
    tag: str | None = None,
) -> Path | None:
    """Send logs to the console and to a fresh timestamped file under ``log_dir``.

    The file copy is always DEBUG regardless of ``verbose``: re-running with more
    logging is often too late, because by then the delivery may be overwritten
    and the local data already changed.

    Args:
        log_dir: Directory for the run log; ``None`` keeps the run console-only.
        name: Command name, used as the log file prefix.
        verbose: Also print DEBUG records on the console.
        tag: Suffix marking what kind of run this was (e.g. ``dryrun``), so a
            directory listing distinguishes rehearsals from runs that wrote data.

    Returns:
        The log file path, or ``None`` when nothing was written to disk.
    """
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(logging.Formatter(_CONSOLE_FORMAT))
    # The root logger passes everything down; each handler filters for itself.
    logging.basicConfig(level=logging.DEBUG, handlers=[console], force=True)
    if log_dir is None:
        return None

    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
    suffix = f"_{tag}" if tag else ""
    log_path = log_dir.resolve() / f"{name}_{timestamp}{suffix}.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
    except OSError as error:
        # Failing to write a log must not abort the command, but staying silent
        # would leave the operator believing there is a record to consult.
        LOG.warning("无法写入日志文件 %s: %s; 本次只输出到控制台", log_path, error)
        return None

    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(_FILE_FORMAT))
    logging.getLogger().addHandler(file_handler)
    return log_path
