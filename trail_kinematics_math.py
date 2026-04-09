"""Numeric trail-kinematics and color mapping helpers."""

from __future__ import annotations

import colorsys
import math

from projection import ProjectedBody
from trail_kinematics_types import (
    BodyTrailKinematics,
    GlobalMetricMaxima,
    KinematicsGeometry,
    KinematicsRuntime,
    RawBodyKinematics,
    TrailColorPolicy,
)


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def empty_raw_kinematics() -> RawBodyKinematics:
    return RawBodyKinematics(hues=[], speeds=[], angular_speeds=[], accels=[])


def trail_segment_kinematics(body: ProjectedBody, geometry: KinematicsGeometry) -> RawBodyKinematics:
    trail_au = body.trail_au
    trail_xy = body.trail_xy
    if len(trail_au) < 2 or len(trail_xy) < 2:
        return empty_raw_kinematics()

    dt_days = max(1e-9, body.trail_step_minutes / (24.0 * 60.0))
    velocities: list[tuple[float, float]] = []
    hues: list[float] = []
    speeds: list[float] = []
    angular_speeds: list[float] = []
    eps = 1e-12

    for i in range(len(trail_au) - 1):
        x0, y0, z0 = trail_au[i]
        x1, y1, z1 = trail_au[i + 1]
        px0, py0 = trail_xy[i]
        px1, py1 = trail_xy[i + 1]

        vx = (x1 - x0) / dt_days
        vy = (y1 - y0) / dt_days
        velocities.append((vx, vy))
        speeds.append(math.hypot(vx, vy))

        dx = px1 - px0
        dy_up = -(py1 - py0)
        px_up = px1 - (0.5 * float(geometry.image_width))
        py_up = (0.5 * float(geometry.image_height)) - py1

        pr = math.hypot(px_up, py_up)
        if pr > eps:
            urx, ury = (px_up / pr, py_up / pr)
        else:
            vm = math.hypot(dx, dy_up)
            if vm > eps:
                urx, ury = (dx / vm, dy_up / vm)
            else:
                urx, ury = (1.0, 0.0)

        utx, uty = (-ury, urx)
        vr = dx * urx + dy_up * ury
        vt = dx * utx + dy_up * uty

        toward = max(0.0, -vr)
        away = max(0.0, vr)
        left = max(0.0, vt)
        right = max(0.0, -vt)

        rr = away + right
        gg = left
        bb = toward
        mx = max(rr, gg, bb)
        if mx <= eps:
            hue = 0.0
        else:
            rr /= mx
            gg /= mx
            bb /= mx
            hue = colorsys.rgb_to_hsv(rr, gg, bb)[0]
        hues.append(hue)

        r0 = math.sqrt(x0 * x0 + y0 * y0 + z0 * z0)
        r1 = math.sqrt(x1 * x1 + y1 * y1 + z1 * z1)
        if r0 <= eps or r1 <= eps:
            angular_speeds.append(0.0)
        else:
            dot = (x0 * x1 + y0 * y1 + z0 * z1) / (r0 * r1)
            dot = max(-1.0, min(1.0, dot))
            dtheta = math.acos(dot)
            angular_speeds.append(dtheta / dt_days)

    accels: list[float] = []
    seg_count = len(velocities)
    if seg_count == 1:
        accels.append(0.0)
    else:
        for i in range(seg_count):
            if i == 0:
                dvx = velocities[1][0] - velocities[0][0]
                dvy = velocities[1][1] - velocities[0][1]
            else:
                dvx = velocities[i][0] - velocities[i - 1][0]
                dvy = velocities[i][1] - velocities[i - 1][1]
            ax = dvx / dt_days
            ay = dvy / dt_days
            accels.append(math.hypot(ax, ay))

    return RawBodyKinematics(hues=hues, speeds=speeds, angular_speeds=angular_speeds, accels=accels)


def segment_color_rgb(
    segment_index: int,
    segment_count: int,
    hue: float,
    speed: float,
    angular_speed: float,
    global_speed_max: float,
    global_angular_speed_max: float,
    body_brightness: float,
    policy: TrailColorPolicy,
) -> tuple[int, int, int]:
    eps = 1e-12
    t = 1.0 if segment_count <= 1 else segment_index / (segment_count - 1)
    t_curved = t ** float(policy.fade_power)
    fade = float(policy.min_fade) + (1.0 - float(policy.min_fade)) * t_curved

    blend = clamp01(float(policy.brightness_angular_blend))
    sat_blend = clamp01(float(policy.saturation_angular_blend))
    sat_linear = clamp01(speed / max(eps, global_speed_max))
    sat_angular = clamp01(angular_speed / max(eps, global_angular_speed_max))
    if bool(policy.dynamic_saturation):
        sat = (1.0 - sat_blend) * sat_linear + sat_blend * sat_angular
    else:
        sat = 1.0

    value_linear = clamp01(speed / max(eps, global_speed_max))
    value_angular = clamp01(angular_speed / max(eps, global_angular_speed_max))
    value_from_speed = (1.0 - blend) * value_linear + blend * value_angular

    body_scale = clamp01(float(body_brightness))
    val = clamp01(value_from_speed * body_scale * fade)

    rr, gg, bb = colorsys.hsv_to_rgb(hue, sat, val)
    return (int(round(rr * 255.0)), int(round(gg * 255.0)), int(round(bb * 255.0)))


def compute_global_metric_maxima(raw_by_body: dict[str, RawBodyKinematics]) -> GlobalMetricMaxima:
    global_speed_max = 0.0
    global_angular_speed_max = 0.0
    global_accel_max = 0.0
    for raw in raw_by_body.values():
        if raw.speeds:
            global_speed_max = max(global_speed_max, max(raw.speeds))
        if raw.angular_speeds:
            global_angular_speed_max = max(global_angular_speed_max, max(raw.angular_speeds))
        if raw.accels:
            global_accel_max = max(global_accel_max, max(raw.accels))

    eps = 1e-12
    return GlobalMetricMaxima(
        speed=max(eps, global_speed_max),
        angular_speed=max(eps, global_angular_speed_max),
        accel=max(eps, global_accel_max),
    )


def materialize_body_kinematics(
    raw_by_body: dict[str, RawBodyKinematics],
    runtime: KinematicsRuntime,
    maxima: GlobalMetricMaxima,
    policy: TrailColorPolicy,
) -> dict[str, BodyTrailKinematics]:
    by_body: dict[str, BodyTrailKinematics] = {}
    for name in runtime.body_names:
        raw = raw_by_body.get(name, empty_raw_kinematics())
        body_brightness = runtime.body_brightness.get(name, 1.0)

        seg_count = len(raw.hues)
        colors: list[tuple[int, int, int]] = []
        for i in range(seg_count):
            colors.append(
                segment_color_rgb(
                    i,
                    seg_count,
                    raw.hues[i],
                    raw.speeds[i],
                    raw.angular_speeds[i],
                    maxima.speed,
                    maxima.angular_speed,
                    body_brightness=body_brightness,
                    policy=policy,
                )
            )
        by_body[name] = BodyTrailKinematics(hue_list=raw.hues, segment_colors=colors)

    return by_body
