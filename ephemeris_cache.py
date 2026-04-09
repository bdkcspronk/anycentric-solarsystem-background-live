"""Persistent trail cache I/O and record conversion helpers."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import numpy as np


CACHE_VERSION = 2
CACHE_PATH = Path(__file__).resolve().parent / "trail_cache.json"


def _cache_file_path() -> str:
    return str(CACHE_PATH)


def load_cache() -> dict:
    path = _cache_file_path()
    if not os.path.exists(path):
        return {"version": CACHE_VERSION, "bodies": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if payload.get("version") != CACHE_VERSION:
            return {"version": CACHE_VERSION, "bodies": {}}
        if not isinstance(payload.get("bodies"), dict):
            return {"version": CACHE_VERSION, "bodies": {}}
        return payload
    except (OSError, json.JSONDecodeError):
        return {"version": CACHE_VERSION, "bodies": {}}


def save_cache(cache: dict) -> None:
    path = _cache_file_path()
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f)
    os.replace(tmp, path)


def cache_record_to_trail(record: dict) -> list[np.ndarray]:
    trail_raw = record.get("trail", [])
    trail: list[np.ndarray] = []
    for vec in trail_raw:
        if not isinstance(vec, list) or len(vec) != 3:
            continue
        trail.append(np.asarray(vec, dtype=float))
    return trail


def trail_to_cache_record(
    trail: list[np.ndarray],
    step_minutes: int,
    sample_count: int,
    last_sample_utc: datetime,
    center_target: str,
) -> dict:
    return {
        "step_minutes": int(step_minutes),
        "sample_count": int(sample_count),
        "last_sample_utc": last_sample_utc.isoformat(),
        "center_target": center_target,
        "trail": [[float(v[0]), float(v[1]), float(v[2])] for v in trail],
    }
