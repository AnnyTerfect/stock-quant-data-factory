"""Conventions shared by every subsystem.

This package holds the vocabulary that ``processing`` and ``quality`` must
agree on: field names, stock-symbol parsing, filesystem layout and logging.
Nothing here reads or writes data files.
"""

from data_factory.core.fields import MINUTE_FIELDS, PRICE_FIELDS
from data_factory.core.layout import (
    FULL_ROOT,
    INCREMENTAL_ROOT,
    MINUTE_FILE_RE,
    OUTPUT_ROOT,
    delivery_dir,
    minute_file_name,
    minute_files,
    minute_relative_dir,
    target_relative_path,
)
from data_factory.core.logging import configure_logging
from data_factory.core.symbols import SYMBOL_RE, parse_symbol, unique_symbol_map

__all__ = [
    "FULL_ROOT",
    "INCREMENTAL_ROOT",
    "MINUTE_FIELDS",
    "MINUTE_FILE_RE",
    "OUTPUT_ROOT",
    "PRICE_FIELDS",
    "SYMBOL_RE",
    "configure_logging",
    "delivery_dir",
    "minute_file_name",
    "minute_files",
    "minute_relative_dir",
    "parse_symbol",
    "target_relative_path",
    "unique_symbol_map",
]
