from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import numpy as np
from skyfield.api import load

import config
import dwarf_planet_orbits


@dataclass(frozen=True)
class BodyState:
    position_au: np.ndarray
    trail_au: list[np.ndarray]
    trail_step_minutes: int


CACHE_VERSION = 2
CACHE_PATH = "trail_cache.json"
DE440S_MIN_UTC = datetime(1849, 12, 26, tzinfo=timezone.utc)


def _ensure_utc(at_time: datetime) -> datetime:
    if at_time.tzinfo is None:
        return at_time.replace(tzinfo=timezone.utc)
    return at_time.astimezone(timezone.utc)


@lru_cache(maxsize=1)
def _get_kernel():
    return load(config.EPHEMERIS_KERNEL)


@lru_cache(maxsize=1)
def _get_timescale():
    return load.timescale()


def _trail_datetimes(at_time: datetime, step_minutes: int) -> list[datetime]:
    step = max(1, int(step_minutes))
    sample_count = max(2, int(_effective_trail_days(at_time) * 24 * 60 / step) + 1)
    return [
        at_time - timedelta(minutes=step * i)
        for i in range(sample_count - 1, -1, -1)
    ]


def _effective_trail_days(at_time: datetime) -> float:
    requested_days = max(0.0, float(config.TRAIL_DAYS))
    # de440s.bsp only supports a finite date range; clamp trailing history
    # to avoid sampling dates before kernel coverage.
    available_days = (at_time - DE440S_MIN_UTC).total_seconds() / 86400.0
    available_days = max(1.0 / 24.0, available_days - 1.0)
    return min(requested_days, available_days)


def _trail_sample_count(step_minutes: int, at_time: datetime) -> int:
    step = max(1, int(step_minutes))
    return max(2, int(_effective_trail_days(at_time) * 24 * 60 / step) + 1)


def _align_time_to_step(utc_time: datetime, step_minutes: int) -> datetime:
    step_seconds = max(60, int(step_minutes) * 60)
    ts = int(utc_time.timestamp())
    aligned = ts - (ts % step_seconds)
    return datetime.fromtimestamp(aligned, tz=timezone.utc)


def _cache_file_path() -> str:
    return os.path.join(os.path.dirname(__file__), CACHE_PATH)


def _load_cache() -> dict:
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


def _save_cache(cache: dict) -> None:
    path = _cache_file_path()
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f)
    os.replace(tmp, path)


def _compute_heliocentric_trail_vectors(target_name: str, kernel, datetimes: list[datetime]) -> list[np.ndarray]:
    if not datetimes:
        return []
    if dwarf_planet_orbits.is_dwarf_planet_body(target_name):
        return dwarf_planet_orbits.get_heliocentric_trail_vectors(target_name, datetimes)

    ts = _get_timescale()
    t_series = ts.from_datetimes(datetimes)
    sun = kernel["sun"]
    ecl_pos = sun.at(t_series).observe(kernel[target_name]).ecliptic_position().au
    vectors = np.asarray(ecl_pos, dtype=float)
    if vectors.ndim == 1:
        vectors = vectors.reshape(3, 1)
    return [vectors[:, i].copy() for i in range(vectors.shape[1])]


def _compute_relative_trail_vectors(
    target_name: str,
    center_name: str,
    kernel,
    datetimes: list[datetime],
) -> list[np.ndarray]:
    target_helio = _compute_heliocentric_trail_vectors(target_name, kernel, datetimes)
    center_helio = _compute_heliocentric_trail_vectors(center_name, kernel, datetimes)
    return [target_vec - center_vec for target_vec, center_vec in zip(target_helio, center_helio)]


def _cache_record_to_trail(record: dict) -> list[np.ndarray]:
    trail_raw = record.get("trail", [])
    trail: list[np.ndarray] = []
    for vec in trail_raw:
        if not isinstance(vec, list) or len(vec) != 3:
            continue
        trail.append(np.asarray(vec, dtype=float))
    return trail


def _trail_to_cache_record(
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


def _build_or_update_trail(
    body_name: str,
    body_target: str,
    center_target: str,
    step_minutes: int,
    sample_count: int,
    aligned_now: datetime,
    kernel,
    cache_bodies: dict,
) -> list[np.ndarray]:
    if body_target.lower() == center_target.lower():
        cache_bodies.pop(body_name, None)
        return [np.zeros(3, dtype=float) for _ in range(sample_count)]

    def recompute_trail(sample_time: datetime) -> list[np.ndarray]:
        datetimes = [sample_time - timedelta(minutes=step_minutes * i) for i in range(sample_count - 1, -1, -1)]
        return _compute_relative_trail_vectors(body_target, center_target, kernel, datetimes)

    record = cache_bodies.get(body_name)
    if not isinstance(record, dict):
        record = None

    if record is None:
        trail = recompute_trail(aligned_now)
        cache_bodies[body_name] = _trail_to_cache_record(trail, step_minutes, sample_count, aligned_now, center_target)
        return trail

    if (
        int(record.get("step_minutes", -1)) != step_minutes
        or int(record.get("sample_count", -1)) != sample_count
        or str(record.get("center_target", "")).lower() != center_target.lower()
    ):
        trail = recompute_trail(aligned_now)
        cache_bodies[body_name] = _trail_to_cache_record(trail, step_minutes, sample_count, aligned_now, center_target)
        return trail

    last_iso = record.get("last_sample_utc")
    if not isinstance(last_iso, str):
        trail = recompute_trail(aligned_now)
        cache_bodies[body_name] = _trail_to_cache_record(trail, step_minutes, sample_count, aligned_now, center_target)
        return trail

    try:
        last_sample = _ensure_utc(datetime.fromisoformat(last_iso))
    except ValueError:
        trail = recompute_trail(aligned_now)
        cache_bodies[body_name] = _trail_to_cache_record(trail, step_minutes, sample_count, aligned_now, center_target)
        return trail

    trail = _cache_record_to_trail(record)
    if len(trail) != sample_count:
        trail = recompute_trail(aligned_now)
        cache_bodies[body_name] = _trail_to_cache_record(trail, step_minutes, sample_count, aligned_now, center_target)
        return trail

    step_delta = int((aligned_now - last_sample).total_seconds() // (step_minutes * 60))
    if step_delta <= 0:
        cache_bodies[body_name] = _trail_to_cache_record(trail, step_minutes, sample_count, last_sample, center_target)
        return trail

    if step_delta >= sample_count:
        trail = recompute_trail(aligned_now)
        cache_bodies[body_name] = _trail_to_cache_record(trail, step_minutes, sample_count, aligned_now, center_target)
        return trail

    new_datetimes = [last_sample + timedelta(minutes=step_minutes * i) for i in range(1, step_delta + 1)]
    new_vectors = _compute_relative_trail_vectors(body_target, center_target, kernel, new_datetimes)
    trail = trail + new_vectors
    trail = trail[-sample_count:]
    cache_bodies[body_name] = _trail_to_cache_record(trail, step_minutes, sample_count, aligned_now, center_target)
    return trail


def is_trail_update_due(at_time: datetime) -> bool:
    """Return True if any body requires one or more new cached trail segments."""
    utc_time = _ensure_utc(at_time)
    cache = _load_cache()
    cache_bodies = cache.get("bodies", {})
    if not isinstance(cache_bodies, dict):
        return True

    center_key = str(config.OBSERVER_CENTER_BODY).strip().lower()
    center_cfg = config.BODIES.get(center_key)
    if center_cfg is None:
        return True
    center_target = center_cfg.target.lower()

    for name, body_cfg in config.BODIES.items():
        if body_cfg.target.lower() == center_target:
            continue

        step_minutes = body_cfg.trail_step_minutes or config.TRAIL_STEP_MINUTES
        sample_count = _trail_sample_count(step_minutes, utc_time)
        aligned_now = _align_time_to_step(utc_time, step_minutes)

        record = cache_bodies.get(name)
        if not isinstance(record, dict):
            return True

        if (
            int(record.get("step_minutes", -1)) != step_minutes
            or int(record.get("sample_count", -1)) != sample_count
            or str(record.get("center_target", "")).lower() != center_target
        ):
            return True

        last_iso = record.get("last_sample_utc")
        if not isinstance(last_iso, str):
            return True
        try:
            last_sample = _ensure_utc(datetime.fromisoformat(last_iso))
        except ValueError:
            return True

        if aligned_now > last_sample:
            return True

    return False


def get_body_states(at_time: datetime) -> dict[str, BodyState]:
    utc_time = _ensure_utc(at_time)
    cache = _load_cache()
    cache_bodies = cache.setdefault("bodies", {})
    kernel = _get_kernel()

    center_key = str(config.OBSERVER_CENTER_BODY).strip().lower()
    center_cfg = config.BODIES.get(center_key)
    if center_cfg is None:
        raise ValueError(f"Center body '{config.OBSERVER_CENTER_BODY}' is not in active BODIES")
    center_target = center_cfg.target.lower()

    states: dict[str, BodyState] = {}
    for name, body_cfg in config.BODIES.items():
        step_minutes = body_cfg.trail_step_minutes or config.TRAIL_STEP_MINUTES
        sample_count = _trail_sample_count(step_minutes, utc_time)
        if body_cfg.target.lower() == center_target:
            cache_bodies.pop(name, None)
            trail = [np.zeros(3, dtype=float) for _ in range(sample_count)]
            position_vec = np.zeros(3, dtype=float)
        else:
            aligned_now = _align_time_to_step(utc_time, step_minutes)
            trail = _build_or_update_trail(
                body_name=name,
                body_target=body_cfg.target,
                center_target=center_target,
                step_minutes=step_minutes,
                sample_count=sample_count,
                aligned_now=aligned_now,
                kernel=kernel,
                cache_bodies=cache_bodies,
            )

            # Keep cache alignment for history, but force the tail sample to exact render time.
            # Use exact render-time position for marker placement without mutating
            # step-aligned trail samples (which keeps segment kinematics/colors stable).
            current_vec = _compute_relative_trail_vectors(
                body_cfg.target,
                center_target,
                kernel,
                [utc_time],
            )[0]
            position_vec = current_vec
        states[name] = BodyState(
            position_au=position_vec,
            trail_au=trail,
            trail_step_minutes=step_minutes,
        )

    _save_cache(cache)
    return states