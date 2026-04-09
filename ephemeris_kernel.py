"""Kernel and time helpers for ephemeris computations."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from skyfield.api import Loader, load

import config


DE440S_MIN_UTC = datetime(1849, 12, 26, tzinfo=timezone.utc)


def ensure_utc(at_time: datetime) -> datetime:
    if at_time.tzinfo is None:
        return at_time.replace(tzinfo=timezone.utc)
    return at_time.astimezone(timezone.utc)


@lru_cache(maxsize=1)
def get_kernel():
    kernel_path = Path(config.EPHEMERIS_KERNEL).expanduser()
    kernel_dir = kernel_path.parent
    kernel_name = kernel_path.name

    kernel_dir.mkdir(parents=True, exist_ok=True)
    loader = Loader(str(kernel_dir))
    return loader(kernel_name)


@lru_cache(maxsize=1)
def get_timescale():
    return load.timescale()
