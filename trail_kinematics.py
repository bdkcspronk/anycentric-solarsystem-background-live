"""Per-segment trail kinematics and color generation with persistent cache."""

from __future__ import annotations

from dataclasses import dataclass
import colorsys
import hashlib
import json
import math
import os

import config
from projection import ProjectedBody


CACHE_VERSION = 4
CACHE_DIR = "trail_kinematics_cache"


@dataclass(frozen=True)
class BodyTrailKinematics:
    hue_list: list[float]
    segment_colors: list[tuple[int, int, int]]


@dataclass(frozen=True)
class TrailKinematicsBundle:
    by_body: dict[str, BodyTrailKinematics]
    global_speed_max: float
    global_angular_speed_max: float
    global_accel_max: float


@dataclass(frozen=True)
class _RawBodyKinematics:
    hues: list[float]
    speeds: list[float]
    angular_speeds: list[float]
    accels: list[float]


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _safe_name(name: str) -> str:
    out = []
    for ch in name:
        if ch.isalnum() or ch in ("-", "_"):
            out.append(ch)
        else:
            out.append("_")
    return "".join(out)


def _body_cache_path(body_name: str, step_minutes: int) -> str:
    base = os.path.join(os.path.dirname(__file__), CACHE_DIR, f"step_{int(step_minutes)}")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, f"{_safe_name(body_name)}.json")


def _body_signature(body: ProjectedBody) -> str:
    h = hashlib.sha256()
    trail = body.trail_au
    trail_xy = body.trail_xy
    n = len(trail)
    h.update(f"step:{body.trail_step_minutes};len:{n}|".encode("ascii"))
    if n:
        x0, y0, z0 = trail[0]
        x1, y1, z1 = trail[-1]
        h.update(f"f:{x0:.9f},{y0:.9f},{z0:.9f}|".encode("ascii"))
        h.update(f"l:{x1:.9f},{y1:.9f},{z1:.9f}|".encode("ascii"))
    if n > 2:
        xm, ym, zm = trail[n // 2]
        h.update(f"m:{xm:.9f},{ym:.9f},{zm:.9f}|".encode("ascii"))
    if trail_xy:
        x0, y0 = trail_xy[0]
        x1, y1 = trail_xy[-1]
        h.update(f"pf:{x0:.6f},{y0:.6f}|".encode("ascii"))
        h.update(f"pl:{x1:.6f},{y1:.6f}|".encode("ascii"))
    if len(trail_xy) > 2:
        xm, ym = trail_xy[len(trail_xy) // 2]
        h.update(f"pm:{xm:.6f},{ym:.6f}|".encode("ascii"))
    return h.hexdigest()


def _trail_segment_kinematics(body: ProjectedBody) -> _RawBodyKinematics:
    trail_au = body.trail_au
    trail_xy = body.trail_xy
    if len(trail_au) < 2 or len(trail_xy) < 2:
        return _RawBodyKinematics(hues=[], speeds=[], angular_speeds=[], accels=[])

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
        # Hue follows apparent vr/vt decomposition in projected Earth-view plane:
        # toward Earth -> blue, away/right -> red, left tangential -> green.
        dx = px1 - px0
        dy_up = -(py1 - py0)
        px_up = px1 - (0.5 * config.IMAGE_WIDTH)
        py_up = (0.5 * config.IMAGE_HEIGHT) - py1

        pr = math.hypot(px_up, py_up)
        if pr > eps:
            urx, ury = (px_up / pr, py_up / pr)
        else:
            vm = math.hypot(dx, dy_up)
            if vm > eps:
                urx, ury = (dx / vm, dy_up / vm)
            else:
                urx, ury = (1.0, 0.0)

        # Tangential unit vector (counter-clockwise around Earth center).
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

    return _RawBodyKinematics(hues=hues, speeds=speeds, angular_speeds=angular_speeds, accels=accels)


def _load_raw_body(body_name: str, step_minutes: int, signature: str) -> _RawBodyKinematics | None:
    path = _body_cache_path(body_name, step_minutes)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    if payload.get("version") != CACHE_VERSION:
        return None
    if payload.get("signature") != signature:
        return None

    try:
        hues = [float(v) for v in payload.get("hues", [])]
        speeds = [float(v) for v in payload.get("speeds", [])]
        angular_speeds = [float(v) for v in payload.get("angular_speeds", [])]
        accels = [float(v) for v in payload.get("accels", [])]
    except (TypeError, ValueError):
        return None

    if not (len(hues) == len(speeds) == len(angular_speeds) == len(accels)):
        return None

    return _RawBodyKinematics(hues=hues, speeds=speeds, angular_speeds=angular_speeds, accels=accels)


def _save_raw_body(body_name: str, step_minutes: int, signature: str, raw: _RawBodyKinematics) -> None:
    path = _body_cache_path(body_name, step_minutes)
    tmp = f"{path}.tmp"
    payload = {
        "version": CACHE_VERSION,
        "signature": signature,
        "hues": raw.hues,
        "speeds": raw.speeds,
        "angular_speeds": raw.angular_speeds,
        "accels": raw.accels,
    }
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp, path)


def _segment_color_rgb(
    segment_index: int,
    segment_count: int,
    hue: float,
    speed: float,
    angular_speed: float,
    accel: float,
    global_speed_max: float,
    global_angular_speed_max: float,
    global_accel_max: float,
    body_brightness: float = 1.0,
) -> tuple[int, int, int]:
    eps = 1e-12
    t = 1.0 if segment_count <= 1 else segment_index / (segment_count - 1)
    t_curved = t ** config.TRAIL_FADE_POWER
    fade = config.TRAIL_MIN_FADE + (1.0 - config.TRAIL_MIN_FADE) * t_curved

    blend = _clamp01(float(config.TRAIL_BRIGHTNESS_ANGULAR_BLEND))
    sat_blend = _clamp01(float(config.TRAIL_SATURATION_ANGULAR_BLEND))
    sat_linear = _clamp01(speed / max(eps, global_speed_max))
    sat_angular = _clamp01(angular_speed / max(eps, global_angular_speed_max))
    if bool(config.TRAIL_DYNAMIC_SATURATION):
        sat = (1.0 - sat_blend) * sat_linear + sat_blend * sat_angular
    else:
        sat = 1.0
    value_linear = _clamp01(speed / max(eps, global_speed_max))
    value_angular = _clamp01(angular_speed / max(eps, global_angular_speed_max))
    value_from_speed = (1.0 - blend) * value_linear + blend * value_angular
    # Use computed per-body brightness (0..1) as the only brightness scale.
    body_scale = _clamp01(float(body_brightness))
    val = _clamp01(value_from_speed * body_scale * fade)

    rr, gg, bb = colorsys.hsv_to_rgb(hue, sat, val)
    return (int(round(rr * 255.0)), int(round(gg * 255.0)), int(round(bb * 255.0)))


def compute_or_load_kinematics(projected: dict[str, ProjectedBody]) -> TrailKinematicsBundle:
    raw_by_body: dict[str, _RawBodyKinematics] = {}
    center_name = str(config.OBSERVER_CENTER_BODY).strip().lower()

    for name in config.BODIES:
        if name == center_name:
            raw_by_body[name] = _RawBodyKinematics(hues=[], speeds=[], angular_speeds=[], accels=[])
            continue

        body = projected.get(name)
        if body is None:
            raw_by_body[name] = _RawBodyKinematics(hues=[], speeds=[], angular_speeds=[], accels=[])
            continue

        sig = _body_signature(body)
        cached = _load_raw_body(name, body.trail_step_minutes, sig)
        if cached is not None:
            raw_by_body[name] = cached
            continue

        raw = _trail_segment_kinematics(body)
        _save_raw_body(name, body.trail_step_minutes, sig, raw)
        raw_by_body[name] = raw

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
    global_speed_max = max(eps, global_speed_max)
    global_angular_speed_max = max(eps, global_angular_speed_max)
    global_accel_max = max(eps, global_accel_max)

    by_body: dict[str, BodyTrailKinematics] = {}
    for name in config.BODIES:
        raw = raw_by_body.get(name, _RawBodyKinematics(hues=[], speeds=[], angular_speeds=[], accels=[]))
        seg_count = len(raw.hues)
        colors: list[tuple[int, int, int]] = []
        for i in range(seg_count):
            body_cfg = config.BODIES.get(name)
            colors.append(
                _segment_color_rgb(
                    i,
                    seg_count,
                    raw.hues[i],
                    raw.speeds[i],
                    raw.angular_speeds[i],
                    raw.accels[i],
                    global_speed_max,
                    global_angular_speed_max,
                    global_accel_max,
                    body_brightness=1.0 if body_cfg is None else float(body_cfg.brightness),
                )
            )
        by_body[name] = BodyTrailKinematics(hue_list=raw.hues, segment_colors=colors)

    return TrailKinematicsBundle(
        by_body=by_body,
        global_speed_max=global_speed_max,
        global_angular_speed_max=global_angular_speed_max,
        global_accel_max=global_accel_max,
    )
