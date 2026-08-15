"""Delivery conventions and tunable thresholds of the ingestion flow.

Adapting to a new delivery structure should start — and preferably end — here.
Names of the local dataset itself are not repeated: they come from
:mod:`data_factory.core.layout`, which both subsystems already agree on.
"""

from __future__ import annotations

from data_factory.core.layout import (
    INDUSTRY_CODE_FILE,
    STOCK_CODE_FILE,
    STOCK_INFO_FILE,
    TRADING_CALENDAR_FILE,
)

# ---------------------------------------------------------------------------
# Archive names inside one delivery directory (e.g. data/incremental/2026-08-08)
# ---------------------------------------------------------------------------

#: Barra risk factors: every delivery carries the full history and overwrites.
BARRA_ARCHIVE_NAME = "barra.zip"

#: Factor database increments: one inner zip per day, merged in date order.
FACTOR_ARCHIVE_NAME = "factorDatabase_incre_pkl.zip"

# ---------------------------------------------------------------------------
# Local dataset conventions
# ---------------------------------------------------------------------------

#: Files delivered as a full snapshot rather than an increment: no date merge,
#: they replace the local copy once the structural checks pass.
FULL_SNAPSHOT_FILES = frozenset(
    {TRADING_CALENDAR_FILE, STOCK_CODE_FILE, STOCK_INFO_FILE}
)

#: Reference files without a date axis; they sit out the date-consistency pass.
NON_DATE_FILES = frozenset({STOCK_CODE_FILE, STOCK_INFO_FILE, INDUSTRY_CODE_FILE})

#: Calendar and look-back window used by the global date-consistency pass.
DATE_REFERENCE_FILE = TRADING_CALENDAR_FILE
DATE_CONSISTENCY_DAYS = 1000

#: How many trading days a matrix may trail the calendar by. Some upstream files
#: (universe, for one) are always published a beat after the bars; as long as the
#: covered range matches the calendar exactly, a small lag only warns.
MAX_DATE_LAG_DAYS = 5

# ---------------------------------------------------------------------------
# Archive resource limits
# ---------------------------------------------------------------------------

# These caps do not judge whether the data is correct; they keep a corrupt or
# hostile archive from exhausting memory and disk before any check runs. The
# values sit deliberately above normal delivery size — raising them should
# follow from inspecting the delivery, not from hitting the limit.
MAX_ARCHIVE_MEMBERS = 20_000
MAX_ARCHIVE_MEMBER_BYTES = 8 * 1024**3
MAX_ARCHIVE_TOTAL_BYTES = 128 * 1024**3
MAX_COMPRESSION_RATIO = 1_000
MAX_INNER_ARCHIVE_BYTES = 8 * 1024**3

# ---------------------------------------------------------------------------
# Comparison parameters
# ---------------------------------------------------------------------------

#: Stock columns compared per chunk. Column counts run in the thousands, and
#: chunking keeps the intermediate matrices at tens of MB instead of copying the
#: whole frame just to compare it.
COLUMN_CHUNK_SIZE = 128

#: How many differing cells to print; enough to locate the problem, not a flood.
MISMATCH_EXAMPLE_LIMIT = 8
