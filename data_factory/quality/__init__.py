"""Public data-quality API.

Every check implements :class:`QualityCheck` and returns a
:class:`QualityReport`; :mod:`data_factory.quality.registry` makes them
discoverable by name.
"""

from data_factory.quality import registry
from data_factory.quality.checks.price_consistency import PriceConsistencyCheck
from data_factory.quality.models import (
    CheckOption,
    CheckSpec,
    CheckStatus,
    DataScope,
    QualityCheck,
    QualityIssue,
    QualityReport,
    run_checks,
)

__all__ = [
    "CheckOption",
    "CheckSpec",
    "CheckStatus",
    "DataScope",
    "PriceConsistencyCheck",
    "QualityCheck",
    "QualityIssue",
    "QualityReport",
    "registry",
    "run_checks",
]
