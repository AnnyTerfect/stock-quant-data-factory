"""Streaming conversion of daily minute-bar pickles."""

from __future__ import annotations

import logging
import os
from collections import deque
from collections.abc import Iterator
from concurrent.futures import Future, ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from data_factory.core.conventions import (
    MINUTE_FIELDS,
    MINUTE_FORMAT,
    PRICE_FIELDS,
    to_integer_dates,
)
from data_factory.core.layout import (
    adjust_factor_file,
    minute_file_date,
    minute_files,
    minute_relative_dir,
)
from data_factory.processing.conversion.manifest import ConversionManifest, group_digest
from data_factory.processing.conversion.models import ConversionConfig
from data_factory.processing.conversion.normalization import normalize_daily_matrix

LOG = logging.getLogger(__name__)


def _prepare_minute_day_worker(
    source: Path, day_factors: pd.DataFrame, stock_codes: pd.Index
) -> dict[str, pd.DataFrame]:
    return prepare_minute_day(source, day_factors, stock_codes)


def _submit_minute_day(
    executor: ProcessPoolExecutor,
    source: Path,
    factors: pd.DataFrame,
    stock_codes: pd.Index,
) -> Future[dict[str, pd.DataFrame]]:
    trade_date = minute_file_date(source)
    if trade_date not in factors.index:
        raise KeyError(f"复权因子中没有交易日 {trade_date}")
    # Passing one row avoids copying the full historical factor matrix into
    # every spawned process.
    return executor.submit(
        _prepare_minute_day_worker,
        source,
        factors.loc[[trade_date]],
        stock_codes,
    )


def _prepared_days(
    sources: list[Path],
    factors: pd.DataFrame,
    stock_codes: pd.Index,
    workers: int,
) -> Iterator[tuple[Path, dict[str, pd.DataFrame]]]:
    """Prepare days concurrently while yielding them in chronological order.

    The bounded queue prevents completed wide frames from consuming memory for
    the entire history when an early day is slower than later ones.
    """
    if workers == 1:
        for source in sources:
            yield source, prepare_minute_day(source, factors, stock_codes)
        return

    executor = ProcessPoolExecutor(
        max_workers=workers,
        mp_context=get_context("spawn"),
    )
    pending: deque[tuple[Path, Future[dict[str, pd.DataFrame]]]] = deque()
    remaining = iter(sources)
    try:
        for source in remaining:
            future = _submit_minute_day(executor, source, factors, stock_codes)
            pending.append((source, future))
            if len(pending) >= workers * 2:
                break

        while pending:
            source, future = pending.popleft()
            yield source, future.result()
            try:
                next_source = next(remaining)
            except StopIteration:
                continue
            pending.append(
                (
                    next_source,
                    _submit_minute_day(executor, next_source, factors, stock_codes),
                )
            )
    finally:
        executor.shutdown(wait=True, cancel_futures=True)


def load_adjustment_factors(input_root: Path) -> pd.DataFrame:
    source = adjust_factor_file(input_root)
    raw = pd.read_pickle(source)
    if not isinstance(raw, pd.DataFrame):
        raise TypeError(f"{source} 不是 DataFrame")
    normalized, was_daily = normalize_daily_matrix(raw)
    if not was_daily:
        raise ValueError(f"{source} 不是日期 × 股票代码的宽表")
    normalized.index = to_integer_dates(normalized.index)
    normalized.index.name = "date"
    return normalized


def minute_datetime(date: pd.Series, time: pd.Series) -> pd.DatetimeIndex:
    """Convert source bar-start labels to canonical bar-end timestamps."""
    text = date.astype("int64").astype(str) + time.astype("int64").astype(
        str
    ).str.zfill(4)
    result = pd.to_datetime(text, format=MINUTE_FORMAT, errors="raise") + pd.Timedelta(
        minutes=1
    )
    return pd.DatetimeIndex(result, name="datetime")


def prepare_minute_day(
    source: Path, factors: pd.DataFrame, stock_codes: pd.Index
) -> dict[str, pd.DataFrame]:
    """Validate, adjust, and pivot one trading day's minute bars."""
    minute = pd.read_pickle(source)
    required = {"code", "date", "time", *MINUTE_FIELDS}
    if not isinstance(minute, pd.DataFrame):
        raise TypeError(f"{source} 不是 DataFrame")
    missing = required.difference(minute.columns)
    if missing:
        raise ValueError(f"{source} 缺少字段: {sorted(missing)}")

    dates = pd.to_numeric(minute["date"], errors="raise").astype("int64")
    unique_dates = dates.unique()
    if len(unique_dates) != 1:
        raise ValueError(
            f"{source} 应只包含一个日期，实际为 {unique_dates[:10].tolist()}"
        )
    trade_date = int(unique_dates[0])
    file_date = minute_file_date(source)
    if file_date is not None and trade_date != file_date:
        raise ValueError(f"{source} 的文件名日期与数据日期 {trade_date} 不一致")
    if trade_date not in factors.index:
        raise KeyError(f"复权因子中没有交易日 {trade_date}")

    codes = pd.to_numeric(minute["code"], errors="coerce")
    valid_code = codes.notna() & codes.between(0, 999999) & codes.eq(codes.round())
    minute = minute.loc[valid_code, ["date", "time", *MINUTE_FIELDS]].copy()
    minute.insert(0, "code", codes.loc[valid_code].astype("int64"))
    minute = minute.loc[minute["code"].isin(stock_codes)]
    if minute.empty:
        raise ValueError(f"{source} 过滤后没有有效股票数据")
    if minute.duplicated(["date", "time", "code"]).any():
        raise ValueError(f"{source} 存在重复的 date/time/code")

    minute["datetime"] = minute_datetime(minute["date"], minute["time"])
    row_factors = minute["code"].map(factors.loc[trade_date])
    for field in PRICE_FIELDS:
        minute[field] = pd.to_numeric(minute[field], errors="coerce") * row_factors

    pivoted = minute.pivot(index="datetime", columns="code", values=list(MINUTE_FIELDS))
    result: dict[str, pd.DataFrame] = {}
    for field in MINUTE_FIELDS:
        wide = pivoted[field].reindex(columns=stock_codes).astype("float64")
        wide.index.name = "datetime"
        wide.columns = pd.Index(stock_codes, dtype="int64", name="stock_code")
        result[field] = wide.sort_index()
    return result


def convert_minute_bars(config: ConversionConfig) -> int:
    """Stream daily long minute bars into six complete wide parquet files.

    The six outputs are one indivisible product of every daily pickle, so the
    whole set of sources is hashed together and rebuilt whenever that hash
    moves: a corrected or newly delivered day cannot be appended to a finished
    parquet file, and leaving the old outputs in place because they exist would
    mean the dataset never sees the day at all.
    """
    minute_relative = minute_relative_dir(config.input_root)
    sources = minute_files(config.input_root / minute_relative)
    if not sources:
        LOG.warning("没有找到 1m bars: %s", config.input_root / minute_relative)
        return 0

    target_root = config.output_root / minute_relative
    targets = {field: target_root / f"{field}.parquet" for field in MINUTE_FIELDS}
    manifest = ConversionManifest.load(config.output_root, config.dry_run)
    key = minute_relative.as_posix()
    digest = group_digest(sources)
    current = not config.overwrite and manifest.is_current(
        key, digest, targets.values()
    )
    if config.dry_run:
        LOG.info("[dry-run] 分钟源文件: %d 个交易日", len(sources))
        if current:
            LOG.info("[dry-run] 分钟源文件未变化，实际执行会跳过")
            return 0
        for field, target in targets.items():
            LOG.info("[dry-run] %s -> %s", field, target)
        return len(sources)
    if current:
        LOG.info("1m bars: 源文件未变化（%d 个交易日），跳过", len(sources))
        return 0
    if any(path.exists() for path in targets.values()):
        LOG.info("1m bars: 源文件已变化，重新生成全部宽表")
    factors = load_adjustment_factors(config.input_root)
    stock_codes = pd.Index(factors.columns, dtype="int64", name="stock_code")
    if config.workers is not None and config.workers < 1:
        raise ValueError("workers 必须大于 0")
    workers = min(
        len(sources),
        config.workers or max(1, (os.process_cpu_count() or 1) // 2),
    )
    LOG.info("1m bars: 使用 %d 个转换进程", workers)
    target_root.mkdir(parents=True, exist_ok=True)
    temporaries = {
        field: path.with_name(path.name + ".tmp") for field, path in targets.items()
    }
    writers: dict[str, pq.ParquetWriter] = {}
    completed = False
    try:
        prepared = _prepared_days(sources, factors, stock_codes, workers)
        for number, (source, frames) in enumerate(prepared, start=1):
            for field, frame in frames.items():
                table = pa.Table.from_pandas(frame, preserve_index=True)
                if field not in writers:
                    writers[field] = pq.ParquetWriter(
                        temporaries[field], table.schema, compression="zstd"
                    )
                writers[field].write_table(table)
            if number == 1 or number % 20 == 0 or number == len(sources):
                LOG.info("1m bars: %d/%d (%s)", number, len(sources), source.name)
        completed = True
    finally:
        for writer in writers.values():
            writer.close()
        if not completed:
            for path in temporaries.values():
                path.unlink(missing_ok=True)

    for field in MINUTE_FIELDS:
        os.replace(temporaries[field], targets[field])
    # Recorded only once all six files are in place: a half-written set has to
    # look unconverted, or the missing fields would be skipped forever.
    manifest.record(key, digest)
    return len(sources)
