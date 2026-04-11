"""Trail layer rendering and cache helpers."""

from __future__ import annotations

import hashlib
import json
import math
import os
import time

from PIL import Image, ImageChops, ImageDraw

import config
from projection import ProjectedBody
from trail_kinematics import TrailKinematicsBundle


TRAIL_LAYER_CACHE_IMAGE = "trail_layer_cache.png"
TRAIL_LAYER_CACHE_META = "trail_layer_cache.json"


def _trail_cache_paths() -> tuple[str, str]:
    base = os.path.dirname(__file__)
    return (
        os.path.join(base, TRAIL_LAYER_CACHE_IMAGE),
        os.path.join(base, TRAIL_LAYER_CACHE_META),
    )


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _distance_point_to_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    abx = bx - ax
    aby = by - ay
    apx = px - ax
    apy = py - ay
    denom = (abx * abx) + (aby * aby)
    if denom <= 1e-12:
        return math.hypot(px - ax, py - ay)
    t = _clamp01(((apx * abx) + (apy * aby)) / denom)
    nx = ax + (abx * t)
    ny = ay + (aby * t)
    return math.hypot(px - nx, py - ny)


def _bend_degrees(ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> float:
    v0x = bx - ax
    v0y = by - ay
    v1x = cx - bx
    v1y = cy - by
    m0 = math.hypot(v0x, v0y)
    m1 = math.hypot(v1x, v1y)
    if m0 <= 1e-12 or m1 <= 1e-12:
        return 0.0
    dot = (v0x * v1x + v0y * v1y) / (m0 * m1)
    dot = max(-1.0, min(1.0, dot))
    return math.degrees(math.acos(dot))


def _initial_coarse_indices(point_count: int, coarse_segments: int) -> list[int]:
    if point_count <= 2:
        return [0, max(0, point_count - 1)]

    max_segment_count = max(1, point_count - 1)
    segment_count = max(1, min(max_segment_count, int(coarse_segments)))
    out = {0, point_count - 1}
    for i in range(1, segment_count):
        idx = int(round((i / float(segment_count)) * (point_count - 1)))
        out.add(max(0, min(point_count - 1, idx)))
    return sorted(out)


def _adaptive_trail_indices(
    trail_xy: list[tuple[float, float]],
    ssaa_scale: int,
    body_name: str,
) -> tuple[list[int], bool]:
    n = len(trail_xy)
    if n <= 2 or not bool(getattr(config, "TRAIL_ADAPTIVE_RENDER", True)):
        return (list(range(n)), False)

    scale = float(max(1, int(ssaa_scale)))
    points = [(p[0] * scale, p[1] * scale) for p in trail_xy]

    coarse_segments = int(getattr(config, "TRAIL_ADAPTIVE_COARSE_SEGMENTS", 12))
    max_segments = max(1, int(getattr(config, "TRAIL_ADAPTIVE_MAX_SEGMENTS_PER_BODY", 450)))
    point_budget = max_segments + 1
    max_error_px = float(getattr(config, "TRAIL_ADAPTIVE_MAX_ERROR_PX", 1.5)) * scale
    min_bend_deg = float(getattr(config, "TRAIL_ADAPTIVE_MIN_BEND_DEG", 4.0))
    min_segment_px = float(getattr(config, "TRAIL_ADAPTIVE_MIN_SEGMENT_PX", 3.0)) * scale

    indices = _initial_coarse_indices(n, coarse_segments)
    seg_budget = max(2, point_budget)

    changed = True
    while changed and len(indices) < seg_budget:
        changed = False
        next_indices = [indices[0]]

        for k in range(len(indices) - 1):
            i0 = indices[k]
            i1 = indices[k + 1]
            if i1 <= i0 + 1:
                next_indices.append(i1)
                continue

            p0 = points[i0]
            p1 = points[i1]
            seg_len = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            if seg_len <= min_segment_px:
                next_indices.append(i1)
                continue

            im = (i0 + i1) // 2
            pm = points[im]

            error_px = _distance_point_to_segment(pm[0], pm[1], p0[0], p0[1], p1[0], p1[1])
            bend_deg = _bend_degrees(p0[0], p0[1], pm[0], pm[1], p1[0], p1[1])

            if (error_px > max_error_px or bend_deg > min_bend_deg) and len(next_indices) < seg_budget:
                if im != next_indices[-1]:
                    next_indices.append(im)
                    changed = True

            next_indices.append(i1)

        indices = sorted(set(next_indices))

    if len(indices) > point_budget:
        # Keep endpoints and uniformly subsample interior points to honor cap.
        keep: set[int] = {indices[0], indices[-1]}
        if point_budget > 2:
            interior = indices[1:-1]
            picks = point_budget - 2
            for i in range(picks):
                src_idx = int(round((i / max(1, picks - 1)) * (len(interior) - 1)))
                keep.add(interior[src_idx])
        indices = sorted(keep)

    hit_segment_cap = (len(indices) - 1) >= max_segments
    if hit_segment_cap and bool(getattr(config, "VERBOSE_LOG", False)):
        print(f"[adaptive-trail] {body_name} reached max segments per body ({max_segments})")

    return (indices, hit_segment_cap)


def _draw_debug_tangent_markers(
    draw: ImageDraw.ImageDraw,
    trail_xy: list[tuple[float, float]],
    draw_indices: list[int],
    ssaa_scale: int,
) -> None:
    if not bool(getattr(config, "TRAIL_DEBUG_SEGMENT_TANGENTS", False)):
        return

    scale = float(max(1, int(ssaa_scale)))
    marker_len = max(1.0, float(getattr(config, "TRAIL_DEBUG_SEGMENT_TANGENT_LENGTH_PX", 28.0)) * scale)
    marker_width = max(1, int(round(float(getattr(config, "TRAIL_DEBUG_SEGMENT_TANGENT_WIDTH_PX", 2.0)) * scale)))
    raw_color = getattr(config, "TRAIL_DEBUG_SEGMENT_TANGENT_COLOR", (255, 255, 255))
    color = tuple(int(max(0, min(255, c))) for c in raw_color)

    if len(draw_indices) < 3:
        return

    half = 0.5 * marker_len
    for j in range(1, len(draw_indices) - 1):
        i_prev = draw_indices[j - 1]
        i_mid = draw_indices[j]
        i_next = draw_indices[j + 1]
        if i_next <= i_prev:
            continue

        x_prev, y_prev = trail_xy[i_prev]
        x_next, y_next = trail_xy[i_next]
        dx = (x_next - x_prev) * scale
        dy = (y_next - y_prev) * scale
        mag = math.hypot(dx, dy)
        if mag <= 1e-9:
            continue

        ux = dx / mag
        uy = dy / mag
        # Draw separator perpendicular to the local tangent.
        nx = -uy
        ny = ux
        x_mid, y_mid = trail_xy[i_mid]
        cx = x_mid * scale
        cy = y_mid * scale

        ax = cx - nx * half
        ay = cy - ny * half
        bx = cx + nx * half
        by = cy + ny * half
        draw.line((ax, ay, bx, by), fill=color, width=marker_width)


def _trail_signature(
    projected: dict[str, ProjectedBody],
    kin_bundle: TrailKinematicsBundle,
    render_width: int,
    render_height: int,
    ssaa_scale: int,
) -> str:
    h = hashlib.sha256()
    trail_line_widths = {
        name: max(1, int(round(config.TRAIL_LINE_WIDTH_PX * math.sqrt(max(1.0, float(body_cfg.marker_radius_px))) * ssaa_scale)))
        for name, body_cfg in config.BODIES.items()
    }
    header = {
        "w": render_width,
        "h": render_height,
        "ssaa": ssaa_scale,
        "trail_line_width_scale": config.TRAIL_LINE_WIDTH_PX,
        "trail_line_widths": trail_line_widths,
        "trail_brightness_angular_blend": config.TRAIL_BRIGHTNESS_ANGULAR_BLEND,
        "trail_min_fade": config.TRAIL_MIN_FADE,
        "trail_fade_power": config.TRAIL_FADE_POWER,
        "trail_adaptive_render": bool(getattr(config, "TRAIL_ADAPTIVE_RENDER", True)),
        "trail_adaptive_coarse_segments": int(getattr(config, "TRAIL_ADAPTIVE_COARSE_SEGMENTS", 12)),
        "trail_adaptive_max_segments_per_body": int(getattr(config, "TRAIL_ADAPTIVE_MAX_SEGMENTS_PER_BODY", 450)),
        "trail_adaptive_max_error_px": float(getattr(config, "TRAIL_ADAPTIVE_MAX_ERROR_PX", 1.5)),
        "trail_adaptive_min_bend_deg": float(getattr(config, "TRAIL_ADAPTIVE_MIN_BEND_DEG", 4.0)),
        "trail_adaptive_min_segment_px": float(getattr(config, "TRAIL_ADAPTIVE_MIN_SEGMENT_PX", 3.0)),
        "trail_debug_segment_tangents": bool(getattr(config, "TRAIL_DEBUG_SEGMENT_TANGENTS", False)),
        "trail_debug_segment_tangent_length_px": float(getattr(config, "TRAIL_DEBUG_SEGMENT_TANGENT_LENGTH_PX", 28.0)),
        "trail_debug_segment_tangent_width_px": float(getattr(config, "TRAIL_DEBUG_SEGMENT_TANGENT_WIDTH_PX", 2.0)),
        "trail_debug_segment_tangent_color": tuple(int(c) for c in getattr(config, "TRAIL_DEBUG_SEGMENT_TANGENT_COLOR", (255, 255, 255))),
        "bodies": list(config.BODIES.keys()),
    }
    h.update(json.dumps(header, sort_keys=True).encode("utf-8"))

    for name in config.BODIES:
        body = projected.get(name)
        body_kin = kin_bundle.by_body.get(name)
        if body is None or body_kin is None:
            continue

        xy = body.trail_xy
        n = len(xy)
        h.update(f"{name}|step:{body.trail_step_minutes}|n:{n}|cn:{len(body_kin.segment_colors)}|".encode("ascii"))
        px, py = body.position_xy
        h.update(f"p:{px:.6f},{py:.6f}|".encode("ascii"))
        if n:
            x0, y0 = xy[0]
            x1, y1 = xy[-1]
            h.update(f"f:{x0:.6f},{y0:.6f}|l:{x1:.6f},{y1:.6f}|".encode("ascii"))
        if n > 2:
            xm, ym = xy[n // 2]
            h.update(f"m:{xm:.6f},{ym:.6f}|".encode("ascii"))

        cols = body_kin.segment_colors
        if cols:
            r0, g0, b0 = cols[0]
            r1, g1, b1 = cols[-1]
            h.update(f"cf:{r0},{g0},{b0}|cl:{r1},{g1},{b1}|".encode("ascii"))
        if len(cols) > 2:
            rm, gm, bm = cols[len(cols) // 2]
            h.update(f"cm:{rm},{gm},{bm}|".encode("ascii"))

    return h.hexdigest()


def _load_cached_trail_layer(signature: str) -> Image.Image | None:
    image_path, meta_path = _trail_cache_paths()
    if not (os.path.exists(image_path) and os.path.exists(meta_path)):
        return None
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        if meta.get("signature") != signature:
            return None
        with Image.open(image_path) as im:
            return im.convert("RGB")
    except (OSError, json.JSONDecodeError):
        return None


def _save_cached_trail_layer(signature: str, image: Image.Image) -> None:
    image_path, meta_path = _trail_cache_paths()
    unique = f"{os.getpid()}_{int(time.time() * 1000)}"
    tmp_img = f"{image_path}.{unique}.tmp"
    tmp_meta = f"{meta_path}.{unique}.tmp"
    image.save(tmp_img, format="PNG")
    with open(tmp_meta, "w", encoding="utf-8") as f:
        json.dump({"signature": signature}, f)

    delays = (0.02, 0.05, 0.1, 0.2, 0.4)
    last_err: OSError | None = None
    for delay in delays:
        try:
            os.replace(tmp_img, image_path)
            os.replace(tmp_meta, meta_path)
            last_err = None
            break
        except OSError as e:
            last_err = e
            time.sleep(delay)

    if last_err is not None:
        try:
            if os.path.exists(tmp_img):
                os.remove(tmp_img)
        except OSError:
            pass
        try:
            if os.path.exists(tmp_meta):
                os.remove(tmp_meta)
        except OSError:
            pass
        raise last_err


def _render_trail_layers(
    projected: dict[str, ProjectedBody],
    kin_bundle: TrailKinematicsBundle,
    render_width: int,
    render_height: int,
    ssaa_scale: int,
) -> Image.Image:
    trail_image = Image.new("RGB", (render_width, render_height), (0, 0, 0))

    for name, body_cfg in config.BODIES.items():
        body = projected[name]
        body_kin = kin_bundle.by_body.get(name)
        if body_kin is None:
            continue

        line_width = max(
            1,
            int(round(config.TRAIL_LINE_WIDTH_PX * math.sqrt(max(1.0, float(body_cfg.marker_radius_px))) * ssaa_scale)),
        )

        trail_xy = body.trail_xy
        colors = body_kin.segment_colors
        if len(trail_xy) < 2 or not colors:
            continue

        draw_indices, _hit_segment_cap = _adaptive_trail_indices(trail_xy, ssaa_scale, name)
        if len(draw_indices) < 2:
            continue

        body_layer = Image.new("RGB", (render_width, render_height), (0, 0, 0))
        d = ImageDraw.Draw(body_layer)
        for s in range(len(draw_indices) - 1):
            i0 = draw_indices[s]
            i1 = draw_indices[s + 1]
            p0 = trail_xy[i0]
            p1 = trail_xy[i1]
            color_idx = max(0, min(len(colors) - 1, i0))
            d.line(
                (p0[0] * ssaa_scale, p0[1] * ssaa_scale, p1[0] * ssaa_scale, p1[1] * ssaa_scale),
                fill=colors[color_idx],
                width=line_width,
            )

            _draw_debug_tangent_markers(d, trail_xy, draw_indices, ssaa_scale)

        if trail_xy and colors:
            tail = trail_xy[-1]
            head = body.position_xy
            d.line(
                (tail[0] * ssaa_scale, tail[1] * ssaa_scale, head[0] * ssaa_scale, head[1] * ssaa_scale),
                fill=colors[-1],
                width=line_width,
            )
        trail_image = ImageChops.add(trail_image, body_layer)

    return trail_image


def get_trail_layer_image(
    projected: dict[str, ProjectedBody],
    kin_bundle: TrailKinematicsBundle,
    render_width: int,
    render_height: int,
    ssaa_scale: int,
) -> Image.Image:
    signature = _trail_signature(projected, kin_bundle, render_width, render_height, ssaa_scale)
    cached = _load_cached_trail_layer(signature)
    if cached is not None:
        return cached

    trail_image = _render_trail_layers(projected, kin_bundle, render_width, render_height, ssaa_scale)
    try:
        _save_cached_trail_layer(signature, trail_image)
    except OSError:
        pass
    return trail_image
