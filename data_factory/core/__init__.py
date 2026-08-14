"""Conventions shared by every subsystem.

This package holds the vocabulary that ``processing`` and ``quality`` must
agree on: field names, stock-symbol parsing, filesystem layout and logging.
Nothing here reads or writes data files.
"""

from data_factory.core.fields import MINUTE_FIELDS, PRICE_FIELDS
from data_factory.core.layout import (
    MINUTE_FILE_RE,
    minute_file_name,
    minute_files,
    minute_relative_dir,
    target_relative_path,
)
from data_factory.core.logging import configure_logging
from data_factory.core.symbols import SYMBOL_RE, parse_symbol, unique_symbol_map

__all__ = [
    "MINUTE_FIELDS",
    "MINUTE_FILE_RE",
    "PRICE_FIELDS",
    "SYMBOL_RE",
    "configure_logging",
    "minute_file_name",
    "minute_files",
    "minute_relative_dir",
    "parse_symbol",
    "target_relative_path",
    "unique_symbol_map",
]
