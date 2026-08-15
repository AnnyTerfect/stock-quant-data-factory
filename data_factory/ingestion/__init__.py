"""Public ingestion API: update the local dataset from one incremental delivery.

Modules bottom-up, each depending only on the ones above it:

===================  ====================================================
Module               Responsibility
===================  ====================================================
``models``           The exception type, the delivery conventions and
                     thresholds, and Tolerance / UpdateConfig / UpdateStats
``storage``          Everything that touches the disk: pickle read and write,
                     the file-name index of the dataset, the staging area
``archives``         Zip traversal, including the nested daily packages
``matrix``           Comparison and merging of date-by-stock matrices
``snapshots``        Validation of the full reference snapshots
``date_consistency`` Trading-day consistency after the update
``sources.*``        Per-source update policies
``service``          Orchestration, and the reporting of one run
===================  ====================================================

``matrix`` and ``snapshots`` provide mechanism only (compare, merge, validate);
whether a difference deserves an error or a warning is policy and lives in
``sources``, where each delivery decides for itself.
"""

from data_factory.ingestion.models import (
    Tolerance,
    UpdateConfig,
    UpdateError,
    UpdateStats,
)
from data_factory.ingestion.service import update_dataset

__all__ = [
    "Tolerance",
    "UpdateConfig",
    "UpdateError",
    "UpdateStats",
    "update_dataset",
]
