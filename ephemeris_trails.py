"""Trail vector computation and incremental update logic."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

import config
import dwarf_planet_orbits
from ephemeris_cache import cache_record_to_trail, trail_to_cache_record
from ephemeris_kernel import DE440S_MIN_UTC, ensure_utc, get_timescale


def effective_trail_days(at_time: datetime) -> float:
    requested_days = max(0.0, float(config.TRAIL_DAYS))
    available_days = (at_time - DE440S_MIN_UTC).total_seconds() / 86400.0
    available_days = max(1.0 / 24.0, available_days - 1.0)
    return min(requested_days, available_days)


def trail_sample_count(step_minutes: int, at_time: datetime, body_name: str | None = None) -> int:
    step = max(1, int(step_minutes))
    days = effective_trail_days(at_time)
    if body_name is not None:
        key = str(body_name).strip().lower()
        body_cap_days = config.BODY_TRAIL_MAX_DAYS.get(key)
        if body_cap_days is not None:
            days = min(days, max(1e-9, float(body_cap_days)))
    return max(2, int(days * 24 * 60 / step) + 1)


def align_time_to_step(utc_time: datetime, step_minutes: int) -> datetime:
    step_seconds = max(60, int(step_minutes) * 60)
    ts = int(utc_time.timestamp())
    aligned = ts - (ts % step_seconds)
    return datetime.fromtimestamp(aligned, tz=utc_time.tzinfo)


def compute_heliocentric_trail_vectors(target_name: str, kernel, datetimes: list[datetime]) -> list[np.ndarray]:
    if not datetimes:
        return []
    if dwarf_planet_orbits.is_dwarf_planet_body(target_name):
        return dwarf_planet_orbits.get_heliocentric_trail_vectors(target_name, datetimes)

    ts = get_timescale()
    t_series = ts.from_datetimes(datetimes)
    sun = kernel["sun"]
    ecl_pos = sun.at(t_series).observe(kernel[target_name]).ecliptic_position().au
    vectors = np.asarray(ecl_pos, dtype=float)
    if vectors.ndim == 1:
        vectors = vectors.reshape(3, 1)
    return [vectors[:, i].copy() for i in range(vectors.shape[1])]


def compute_relative_trail_vectors(
    target_name: str,
    center_name: str,
    kernel,
    datetimes: list[datetime],
) -> list[np.ndarray]:
    target_helio = compute_heliocentric_trail_vectors(target_name, kernel, datetimes)
    center_helio = compute_heliocentric_trail_vectors(center_name, kernel, datetimes)
    return [target_vec - center_vec for target_vec, center_vec in zip(target_helio, center_helio)]


def build_or_update_trail(
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
        return compute_relative_trail_vectors(body_target, center_target, kernel, datetimes)

    record = cache_bodies.get(body_name)
    if not isinstance(record, dict):
        record = None

    if record is None:
        trail = recompute_trail(aligned_now)
        cache_bodies[body_name] = trail_to_cache_record(trail, step_minutes, sample_count, aligned_now, center_target)
        return trail

    if (
        int(record.get("step_minutes", -1)) != step_minutes
        or int(record.get("sample_count", -1)) != sample_count
        or str(record.get("center_target", "")).lower() != center_target.lower()
    ):
        trail = recompute_trail(aligned_now)
        cache_bodies[body_name] = trail_to_cache_record(trail, step_minutes, sample_count, aligned_now, center_target)
        return trail

    last_iso = record.get("last_sample_utc")
    if not isinstance(last_iso, str):
        trail = recompute_trail(aligned_now)
        cache_bodies[body_name] = trail_to_cache_record(trail, step_minutes, sample_count, aligned_now, center_target)
        return trail

    try:
        last_sample = ensure_utc(datetime.fromisoformat(last_iso))
    except ValueError:
        trail = recompute_trail(aligned_now)
        cache_bodies[body_name] = trail_to_cache_record(trail, step_minutes, sample_count, aligned_now, center_target)
        return trail

    trail = cache_record_to_trail(record)
    if len(trail) != sample_count:
        trail = recompute_trail(aligned_now)
        cache_bodies[body_name] = trail_to_cache_record(trail, step_minutes, sample_count, aligned_now, center_target)
        return trail

    step_delta = int((aligned_now - last_sample).total_seconds() // (step_minutes * 60))
    if step_delta <= 0:
        cache_bodies[body_name] = trail_to_cache_record(trail, step_minutes, sample_count, last_sample, center_target)
        return trail

    if step_delta >= sample_count:
        trail = recompute_trail(aligned_now)
        cache_bodies[body_name] = trail_to_cache_record(trail, step_minutes, sample_count, aligned_now, center_target)
        return trail

    new_datetimes = [last_sample + timedelta(minutes=step_minutes * i) for i in range(1, step_delta + 1)]
    new_vectors = compute_relative_trail_vectors(body_target, center_target, kernel, new_datetimes)
    trail = trail + new_vectors
    trail = trail[-sample_count:]
    cache_bodies[body_name] = trail_to_cache_record(trail, step_minutes, sample_count, aligned_now, center_target)
    return trail
