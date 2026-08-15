"""One module per delivered archive, each with its own update policy.

Every source exposes the same ``update(...)`` entry point: it validates its input
and registers the results in the staging area, but never writes to the dataset.
Landing the files is triggered once, by
:mod:`data_factory.ingestion.service`, after every check has passed.
"""
