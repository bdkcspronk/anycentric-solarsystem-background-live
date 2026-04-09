"""Trail kinematics orchestration with persistent cache."""

from __future__ import annotations

import config
from projection import ProjectedBody
from trail_kinematics_cache import RawKinematicsCache, body_signature
from trail_kinematics_math import (
    compute_global_metric_maxima,
    empty_raw_kinematics,
    materialize_body_kinematics,
    trail_segment_kinematics,
)
from trail_kinematics_types import (
    BodyTrailKinematics,
    GlobalMetricMaxima,
    KinematicsGeometry,
    KinematicsRuntime,
    RawBodyKinematics,
    TrailColorPolicy,
    TrailKinematicsBundle,
)


def _runtime_geometry() -> KinematicsGeometry:
    return KinematicsGeometry(
        image_width=max(1, int(config.IMAGE_WIDTH)),
        image_height=max(1, int(config.IMAGE_HEIGHT)),
    )


def _runtime_color_policy() -> TrailColorPolicy:
    return TrailColorPolicy(
        fade_power=float(config.TRAIL_FADE_POWER),
        min_fade=float(config.TRAIL_MIN_FADE),
        dynamic_saturation=bool(config.TRAIL_DYNAMIC_SATURATION),
        saturation_angular_blend=float(config.TRAIL_SATURATION_ANGULAR_BLEND),
        brightness_angular_blend=float(config.TRAIL_BRIGHTNESS_ANGULAR_BLEND),
    )


def _runtime_context() -> KinematicsRuntime:
    body_names = tuple(config.BODIES.keys())
    center_name = str(config.OBSERVER_CENTER_BODY).strip().lower()
    body_brightness = {
        name: float(body_cfg.brightness)
        for name, body_cfg in config.BODIES.items()
    }
    return KinematicsRuntime(
        body_names=body_names,
        center_name=center_name,
        body_brightness=body_brightness,
    )


def _compute_raw_by_body(
    projected: dict[str, ProjectedBody],
    runtime: KinematicsRuntime,
    geometry: KinematicsGeometry,
    cache: RawKinematicsCache,
) -> dict[str, RawBodyKinematics]:
    raw_by_body: dict[str, RawBodyKinematics] = {}
    for name in runtime.body_names:
        if name == runtime.center_name:
            raw_by_body[name] = empty_raw_kinematics()
            continue

        body = projected.get(name)
        if body is None:
            raw_by_body[name] = empty_raw_kinematics()
            continue

        sig = body_signature(body)
        cached = cache.load(name, body.trail_step_minutes, sig)
        if cached is not None:
            raw_by_body[name] = cached
            continue

        raw = trail_segment_kinematics(body, geometry)
        cache.save(name, body.trail_step_minutes, sig, raw)
        raw_by_body[name] = raw

    return raw_by_body


def compute_or_load_kinematics(projected: dict[str, ProjectedBody]) -> TrailKinematicsBundle:
    runtime = _runtime_context()
    geometry = _runtime_geometry()
    policy = _runtime_color_policy()
    cache = RawKinematicsCache()

    raw_by_body = _compute_raw_by_body(projected, runtime, geometry, cache)
    maxima: GlobalMetricMaxima = compute_global_metric_maxima(raw_by_body)
    by_body: dict[str, BodyTrailKinematics] = materialize_body_kinematics(raw_by_body, runtime, maxima, policy)

    return TrailKinematicsBundle(
        by_body=by_body,
        global_speed_max=maxima.speed,
        global_angular_speed_max=maxima.angular_speed,
        global_accel_max=maxima.accel,
    )


__all__ = [
    "BodyTrailKinematics",
    "TrailKinematicsBundle",
    "compute_or_load_kinematics",
]
