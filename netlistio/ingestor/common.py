"""
Shared utilities for parser components.

Provides common functionality like memory-mapped file handling used
across scanner and parser implementations.
"""

import contextlib
import mmap
from pathlib import Path
from typing import Iterator

__all__ = ["open_mmap"]


@contextlib.contextmanager
def open_mmap(filepath: str | Path) -> Iterator[mmap.mmap]:
    with open(
        filepath,
        "r+b",
    ) as f, mmap.mmap(
        f.fileno(),
        0,
        access=mmap.ACCESS_READ,
    ) as mm:
        yield mm
