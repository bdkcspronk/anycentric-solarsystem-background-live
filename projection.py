"""Projection pipeline from AU coordinates to on-screen positions."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import math

import config
from ephemeris import BodyState


@dataclass(frozen=True)
class ProjectedBody:
    position_au: tuple[float, float, float]
    position_xy: tuple[float, float]
    trail_xy: list[tuple[float, float]]
    trail_au: list[tuple[float, float, float]]
    trail_step_minutes: int


def _rotate_view(x: float, y: float, z: float) -> tuple[float, float, float]:
    m = _rotation_matrix(config.VIEW_YAW_DEG, config.VIEW_PITCH_DEG, config.VIEW_ROLL_DEG)
    return (
        m[0] * x + m[1] * y + m[2] * z,
        m[3] * x + m[4] * y + m[5] * z,
        m[6] * x + m[7] * y + m[8] * z,
    )


@lru_cache(maxsize=64)
def _rotation_matrix(yaw_deg: float, pitch_deg: float, roll_deg: float) -> tuple[float, float, float, float, float, float, float, float, float]:
    """Return composed yaw/pitch/roll matrix matching legacy rotation order.

    Order is yaw(z) -> pitch(x) -> roll(y), equivalent to the original
    sequential scalar rotation implementation.
    """

    yaw = math.radians(float(yaw_deg))
    pitch = math.radians(float(pitch_deg))
    roll = math.radians(float(roll_deg))

    cy = math.cos(yaw)
    sy = math.sin(yaw)
    cp = math.cos(pitch)
    sp = math.sin(pitch)
    cr = math.cos(roll)
    sr = math.sin(roll)

    # R = Ry(roll) * Rx(pitch) * Rz(yaw)
    return (
        cr * cy + sr * sp * sy,
        -cr * sy + sr * sp * cy,
        sr * cp,
        cp * sy,
        cp * cy,
        -sp,
        -sr * cy + cr * sp * sy,
        sr * sy + cr * sp * cy,
        cr * cp,
    )


def _to_visual_xy_au(x_au: float, y_au: float, z_au: float, body_name: str) -> tuple[float, float]:
    x_au, y_au, z_au = _rotate_view(x_au, y_au, z_au)

    r = math.hypot(x_au, y_au)
    if r > 0.0:
        mode = config.ORBIT_RADIUS_MODE.lower()
        if mode == "power":
            visual_r = r ** config.ORBIT_RADIUS_POWER
        elif mode == "sqrt":
            visual_r = math.sqrt(r)
        elif mode == "log":
            visual_r = math.log1p(r)
        else:
            visual_r = r

        visual_r *= config.BODY_DISTANCE_MULTIPLIERS.get(body_name, 1.0)
        stretch = visual_r / r
        x_au *= stretch
        y_au *= stretch

    return (x_au, y_au)


def _project_au_to_px(
    x_au: float,
    y_au: float,
    z_au: float,
    body_name: str,
    scale: float,
) -> tuple[float, float]:
    x_au, y_au = _to_visual_xy_au(x_au, y_au, z_au, body_name)

    half_w = config.IMAGE_WIDTH / 2.0
    half_h = config.IMAGE_HEIGHT / 2.0

    x_px = half_w + x_au * scale
    y_px = half_h - y_au * scale
    return (x_px, y_px)


def _compute_projection_scale(states: dict[str, BodyState]) -> float:
    fill = max(1e-3, min(1.0, float(config.WORLD_VIEW_FILL_FRACTION)))
    max_abs_x = 0.0
    max_abs_y = 0.0

    # Fit based on full trail extents so both bodies and their paths are in-frame.
    for name in config.BODIES:
        body = states.get(name)
        if body is None:
            continue

        samples = body.trail_au if body.trail_au else [body.position_au]
        for v in samples:
            x_au, y_au = _to_visual_xy_au(
                float(v[0]),
                float(v[1]),
                float(v[2]),
                name,
            )
            max_abs_x = max(max_abs_x, abs(x_au))
            max_abs_y = max(max_abs_y, abs(y_au))

    half_w = config.IMAGE_WIDTH * 0.5
    half_h = config.IMAGE_HEIGHT * 0.5
    sx = half_w / max(1e-12, max_abs_x)
    sy = half_h / max(1e-12, max_abs_y)
    scale = fill * min(sx, sy)

    if scale <= 1e-12:
        fallback_radius = max(1e-12, float(config.WORLD_RADIUS_AU))
        return min(config.IMAGE_WIDTH, config.IMAGE_HEIGHT) * 0.5 / fallback_radius

    return scale


def project_states(states: dict[str, BodyState]) -> dict[str, ProjectedBody]:
    scale = _compute_projection_scale(states)
    projected: dict[str, ProjectedBody] = {}
    for name, body in states.items():
        position_au = (
            float(body.position_au[0]),
            float(body.position_au[1]),
            float(body.position_au[2]),
        )
        position_xy = _project_au_to_px(position_au[0], position_au[1], position_au[2], name, scale)
        trail_xy = [
            _project_au_to_px(float(v[0]), float(v[1]), float(v[2]), name, scale)
            for v in body.trail_au
        ]
        trail_au = [(float(v[0]), float(v[1]), float(v[2])) for v in body.trail_au]
        projected[name] = ProjectedBody(
            position_au=position_au,
            position_xy=position_xy,
            trail_xy=trail_xy,
            trail_au=trail_au,
            trail_step_minutes=body.trail_step_minutes,
        )
    return projected