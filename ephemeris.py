"""Ephemeris orchestration for observer-centered body states."""

from __future__ import annotations

from datetime import datetime

import numpy as np

import config
from ephemeris_cache import load_cache, save_cache
from ephemeris_kernel import ensure_utc, get_kernel
from ephemeris_trails import (
    align_time_to_step,
    build_or_update_trail,
    compute_heliocentric_trail_vectors,
    trail_sample_count,
)
from ephemeris_types import BodyState


def is_trail_update_due(at_time) -> bool:
    """Return True if any body requires one or more new cached trail segments."""
    utc_time = ensure_utc(at_time)
    cache = load_cache()
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
        sample_count = trail_sample_count(step_minutes, utc_time)
        aligned_now = align_time_to_step(utc_time, step_minutes)

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
            last_sample = ensure_utc(datetime.fromisoformat(last_iso))
        except ValueError:
            return True

        if aligned_now > last_sample:
            return True

    return False


def get_body_states(at_time) -> dict[str, BodyState]:
    utc_time = ensure_utc(at_time)
    cache = load_cache()
    cache_bodies = cache.setdefault("bodies", {})
    kernel = get_kernel()

    center_key = str(config.OBSERVER_CENTER_BODY).strip().lower()
    center_cfg = config.BODIES.get(center_key)
    if center_cfg is None:
        raise ValueError(f"Center body '{config.OBSERVER_CENTER_BODY}' is not in active BODIES")

    center_target = center_cfg.target.lower()
    center_current_vec = compute_heliocentric_trail_vectors(center_target, kernel, [utc_time])[0]

    states: dict[str, BodyState] = {}
    for name, body_cfg in config.BODIES.items():
        step_minutes = body_cfg.trail_step_minutes or config.TRAIL_STEP_MINUTES
        sample_count = trail_sample_count(step_minutes, utc_time)

        if body_cfg.target.lower() == center_target:
            cache_bodies.pop(name, None)
            trail = [np.zeros(3, dtype=float) for _ in range(sample_count)]
            position_vec = np.zeros(3, dtype=float)
        else:
            aligned_now = align_time_to_step(utc_time, step_minutes)
            trail = build_or_update_trail(
                body_name=name,
                body_target=body_cfg.target,
                center_target=center_target,
                step_minutes=step_minutes,
                sample_count=sample_count,
                aligned_now=aligned_now,
                kernel=kernel,
                cache_bodies=cache_bodies,
            )
            target_current = compute_heliocentric_trail_vectors(body_cfg.target, kernel, [utc_time])[0]
            position_vec = target_current - center_current_vec

        states[name] = BodyState(
            position_au=position_vec,
            trail_au=trail,
            trail_step_minutes=step_minutes,
        )

    save_cache(cache)
    return states

__all__ = ["BodyState", "is_trail_update_due", "get_body_states"]
