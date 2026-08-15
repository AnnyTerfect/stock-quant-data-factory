"""The single exception type of the ingestion flow."""

from __future__ import annotations


class UpdateError(RuntimeError):
    """Raised when the data cannot be updated safely.

    It separates "the data is wrong" from "the program is wrong": the command
    line turns an :class:`UpdateError` into one concise line plus a non-zero
    exit code, while every other exception keeps its traceback.
    """
