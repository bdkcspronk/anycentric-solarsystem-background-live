from __future__ import annotations

from dataclasses import dataclass
import math

import config
from ephemeris import BodyState


@dataclass(frozen=True)
class ProjectedBody:
    position_xy: tuple[float, float]
    trail_xy: list[tuple[float, float]]
    trail_au: list[tuple[float, float, float]]
    trail_step_minutes: int


def _rotate_view(x: float, y: float, z: float) -> tuple[float, float, float]:
    yaw = math.radians(config.VIEW_YAW_DEG)
    pitch = math.radians(config.VIEW_PITCH_DEG)
    roll = math.radians(config.VIEW_ROLL_DEG)

    cy = math.cos(yaw)
    sy = math.sin(yaw)
    x, y = (cy * x - sy * y, sy * x + cy * y)

    cp = math.cos(pitch)
    sp = math.sin(pitch)
    y, z = (cp * y - sp * z, sp * y + cp * z)

    cr = math.cos(roll)
    sr = math.sin(roll)
    x, z = (cr * x + sr * z, -sr * x + cr * z)

    return (x, y, z)


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
        trail_xy = [
            _project_au_to_px(float(v[0]), float(v[1]), float(v[2]), name, scale)
            for v in body.trail_au
        ]
        trail_au = [(float(v[0]), float(v[1]), float(v[2])) for v in body.trail_au]
        projected[name] = ProjectedBody(
            position_xy=trail_xy[-1],
            trail_xy=trail_xy,
            trail_au=trail_au,
            trail_step_minutes=body.trail_step_minutes,
        )
    return projected