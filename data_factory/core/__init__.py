"""Conventions shared by every subsystem.

This package holds the vocabulary that ``ingestion``, ``processing`` and
``quality`` must agree on: field names, stock-symbol parsing, trading-date
parsing, filesystem layout and logging. Nothing here reads or writes data
files.

Import from the modules directly (``from data_factory.core.layout import
FULL_ROOT``) rather than from this package: the subsystems each need a
different slice of the vocabulary, and a re-export list here would only be one
more place to keep in sync.
"""
