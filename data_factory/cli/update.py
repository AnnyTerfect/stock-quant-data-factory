"""Command-line entry point for incremental dataset updates."""

from __future__ import annotations

import argparse
import logging
import pickle
import zipfile
from pathlib import Path

from data_factory.core.layout import FULL_ROOT, delivery_dir
from data_factory.ingestion import Tolerance, UpdateConfig, UpdateError, update_dataset

LOG = logging.getLogger(__name__)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Register update arguments on a command parser."""
    parser.add_argument(
        "--delivery",
        type=Path,
        required=True,
        help="交付目录，或 data/incremental 下的交付名（如 2026-08-08）",
    )
    parser.add_argument(
        "--data", type=Path, default=FULL_ROOT, help="要更新的数据根目录"
    )
    parser.add_argument("--rtol", type=float, default=1e-7, help="历史比较的相对容差")
    parser.add_argument("--atol", type=float, default=1e-7, help="历史比较的绝对容差")
    parser.add_argument(
        "--dry-run", action="store_true", help="只校验和合并，不替换任何目标文件"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="控制台输出 DEBUG 日志（日志文件不受影响）",
    )
    # Unpickling executes code, so trusting the delivery is a deliberate act and
    # never a default; the flag cannot make an unknown delivery safe.
    parser.add_argument(
        "--trusted-pickle",
        action="store_true",
        help="确认交付 pickle 来自可信来源；未确认时拒绝反序列化",
    )


def run(args: argparse.Namespace) -> None:
    """Execute a parsed update command."""
    config = UpdateConfig(
        delivery_dir=delivery_dir(args.delivery),
        data_root=args.data,
        tolerance=Tolerance(rtol=args.rtol, atol=args.atol),
        dry_run=args.dry_run,
        trusted_pickle=args.trusted_pickle,
    )
    try:
        stats = update_dataset(config)
    except (UpdateError, zipfile.BadZipFile, pickle.UnpicklingError) as error:
        # A data problem gets one line of conclusion; its traceback helps nobody.
        LOG.error("更新终止: %s", error)
        raise SystemExit(2) from None

    if stats.error_count:
        raise SystemExit(2)
