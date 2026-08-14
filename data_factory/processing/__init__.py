"""Public data-processing API.

Callers should import from this module rather than from implementation modules.
"""

from data_factory.processing.minute import convert_minute_bars, prepare_minute_day
from data_factory.processing.models import (
    ConversionConfig,
    ConversionPart,
    ConversionResult,
)
from data_factory.processing.normalization import normalize_daily_matrix
from data_factory.processing.paths import target_relative_path
from data_factory.processing.regular import convert_regular_pickles, copy_other_files
from data_factory.processing.service import convert_dataset

__all__ = [
    "ConversionConfig",
    "ConversionPart",
    "ConversionResult",
    "convert_dataset",
    "convert_minute_bars",
    "convert_regular_pickles",
    "copy_other_files",
    "normalize_daily_matrix",
    "prepare_minute_day",
    "target_relative_path",
]
