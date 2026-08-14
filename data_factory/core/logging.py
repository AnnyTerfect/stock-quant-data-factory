"""Logging setup shared by every command."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path


def configure_logging(log_dir: Path, name: str) -> Path:
    """Send logs to the console and to a fresh timestamped file under ``log_dir``."""
    log_dir = log_dir.resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
    log_path = log_dir / f"{name}_{timestamp}.log"
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logging.basicConfig(
        level=logging.INFO, handlers=[console, file_handler], force=True
    )
    return log_path
