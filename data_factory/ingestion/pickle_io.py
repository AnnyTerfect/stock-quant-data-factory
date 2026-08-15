"""Pickle reading and writing."""

from __future__ import annotations

import os
import pickle
from pathlib import Path
from typing import BinaryIO

import pandas as pd

from data_factory.ingestion.errors import UpdateError


def load_pickle(source: Path | BinaryIO) -> object:
    """Read one pickled object from a path or an already open binary stream.

    Streams are accepted so that zip members can be read without landing on disk.
    """
    try:
        return pd.read_pickle(source)
    except (
        pickle.UnpicklingError,
        EOFError,
        AttributeError,
        ImportError,
        IndexError,
    ) as error:
        label = str(source) if isinstance(source, Path) else "压缩包成员"
        raise UpdateError(f"{label}: pickle 无法反序列化: {error}") from error


def dump_pickle(value: object, destination: Path) -> None:
    """Write ``value`` to ``destination`` atomically.

    A ``.writing`` sibling is filled first and then renamed, so an interrupted
    write leaves the destination holding either the old or the new content —
    never half a file.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".writing")
    pd.to_pickle(value, temporary)
    os.replace(temporary, destination)
