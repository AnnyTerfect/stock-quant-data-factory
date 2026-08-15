"""Public ingestion API: update the local dataset from one incremental delivery.

Modules bottom-up, each depending only on the ones above it:

===================  ====================================================
Module               Responsibility
===================  ====================================================
``errors``           The single exception type
``conventions``      Delivery naming conventions and thresholds
``models``           Tolerance / UpdateConfig / UpdateStats
``pickle_io``        Pickle reading and writing
``archives``         Zip traversal, including the nested daily packages
``catalog``          File-name index of the local dataset
``matrix``           Comparison and merging of date-by-stock matrices
``snapshots``        Validation of the full reference snapshots
``date_consistency`` Trading-day consistency after the update
``staging``          Staging area, committed once everything passes
``report``           Collecting and presenting the issues of one run
``sources.*``        Per-source update policies
``service``          Orchestration
===================  ====================================================

``matrix`` and ``snapshots`` provide mechanism only (compare, merge, validate);
whether a difference deserves an error or a warning is policy and lives in
``sources``, where each delivery decides for itself.
"""

from data_factory.ingestion.errors import UpdateError
from data_factory.ingestion.models import Tolerance, UpdateConfig, UpdateStats
from data_factory.ingestion.service import update_dataset

__all__ = [
    "Tolerance",
    "UpdateConfig",
    "UpdateError",
    "UpdateStats",
    "update_dataset",
]
