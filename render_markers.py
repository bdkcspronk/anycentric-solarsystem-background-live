"""Marker and label drawing for projected bodies."""

from __future__ import annotations

import math

from PIL import Image, ImageChops, ImageDraw

import config
import dwarf_planet_orbits
from projection import ProjectedBody
from render_utils import clamp01, get_label_font, revalue_rgb
from trail_kinematics import TrailKinematicsBundle


MarkerRow = tuple[str, ProjectedBody, config.BodyConfig, float, float, float, tuple[int, int, int]]


def _scale_position(position_xy: tuple[float, float], scale: int) -> tuple[float, float]:
    x, y = position_xy
    return x * scale, y * scale


def _resolve_marker_color(
    name: str,
    body_cfg: config.BodyConfig,
    kin_bundle: TrailKinematicsBundle,
    center_name: str,
) -> tuple[int, int, int]:
    if name == center_name:
        return (255, 255, 255)

    body_kin = kin_bundle.by_body.get(name)
    if body_kin and body_kin.segment_colors:
        idx = -2 if len(body_kin.segment_colors) >= 2 else -1
        return revalue_rgb(body_kin.segment_colors[idx], body_cfg.brightness)

    bv = int(round(clamp01(float(body_cfg.brightness)) * 255.0))
    return (bv, bv, bv)


def _apply_orbit_radius_mapping(value: float) -> float:
    v = max(0.0, float(value))
    mode = str(config.ORBIT_RADIUS_MODE).strip().lower()
    if mode == "power":
        return v ** max(1e-6, float(config.ORBIT_RADIUS_POWER))
    if mode == "sqrt":
        return math.sqrt(v)
    if mode == "log":
        return math.log1p(v)
    return v


def _marker_gamma_exponent() -> float:
    factor = max(0.5, float(config.BODY_MARKER_RADIUS_POWER_FACTOR))
    return 1.0 / factor


def _linear_marker_metric(name: str, center_name: str) -> float:
    metric = max(0.0, float(config.BODY_MARKER_RADIUS.get(name, 0.0)))
    if name == center_name and bool(getattr(config, "BODY_MARKER_CENTER_MAP_WITH_ORBIT_MODE", True)):
        return _apply_orbit_radius_mapping(metric)
    return metric


def _build_angular_marker_metrics(
    projected: dict[str, ProjectedBody],
    center_name: str,
) -> dict[str, float]:
    angular_raw: dict[str, float] = {}

    for name in config.BODIES:
        if name == center_name:
            continue

        body = projected.get(name)
        if body is None:
            continue

        x_au, y_au, z_au = body.position_au
        distance_au = math.sqrt((x_au * x_au) + (y_au * y_au) + (z_au * z_au))
        if distance_au <= 1e-12:
            angular_raw[name] = 0.0
            continue

        radius_ratio_to_sun = max(0.0, float(config.BODY_MARKER_RADIUS.get(name, 0.0)))
        angular_raw[name] = radius_ratio_to_sun / distance_au

    max_angular = max(angular_raw.values(), default=0.0)
    if max_angular <= 1e-12:
        return {name: 0.0 for name in angular_raw}

    return {name: (value / max_angular) for name, value in angular_raw.items()}


def _resolve_marker_radius(
    name: str,
    center_name: str,
    angular_metrics: dict[str, float],
    ssaa_scale: int,
) -> float:
    mode = str(getattr(config, "BODY_MARKER_SIZE_MODE", "linear")).strip().lower()
    if mode == "angular" and name != center_name:
        metric = max(0.0, float(angular_metrics.get(name, 0.0)))
    else:
        metric = _linear_marker_metric(name, center_name)

    marker_scale = max(0.0, float(config.BODY_MARKER_SCALE))
    radius_px = (metric ** _marker_gamma_exponent()) * marker_scale
    return radius_px * ssaa_scale


def _build_marker_rows(
    projected: dict[str, ProjectedBody],
    kin_bundle: TrailKinematicsBundle,
    ssaa_scale: int,
) -> list[MarkerRow]:
    rows: list[MarkerRow] = []
    center_name = str(config.OBSERVER_CENTER_BODY).strip().lower()
    angular_metrics = _build_angular_marker_metrics(projected, center_name)

    for name, body_cfg in config.BODIES.items():
        body = projected[name]
        sx, sy = _scale_position(body.position_xy, ssaa_scale)
        r = _resolve_marker_radius(name, center_name, angular_metrics, ssaa_scale)
        color = _resolve_marker_color(name, body_cfg, kin_bundle, center_name)
        rows.append((name, body, body_cfg, sx, sy, r, color))

    return rows


def _draw_single_glow(gdraw: ImageDraw.ImageDraw, sx: float, sy: float, r: float, color: tuple[int, int, int], brightness: float) -> None:
    b = clamp01(float(brightness))
    if b <= 0.0:
        return

    glow_strength = b ** 2.0
    if glow_strength <= 1e-6:
        return

    base_r = max(24.0, 5 * float(r))
    outer_r = base_r * (1.6 + 2.2 * glow_strength)

    peak_alpha = int(round(88.0 * glow_strength))
    peak_alpha = max(0, min(128, peak_alpha))

    rings = 32
    for i in range(rings, 0, -1):
        t = i / float(rings)
        rr = outer_r * t
        inner_weight = 1.0 - t
        alpha = int(round(peak_alpha * (0.8 * (inner_weight ** 1.7))))

        if alpha <= 0:
            continue

        gdraw.ellipse(
            (sx - rr, sy - rr, sx + rr, sy + rr),
            fill=(*color, max(0, min(255, alpha))),
        )


def _draw_marker_glow(image: Image.Image, marker_rows: list[MarkerRow]) -> None:
    glow_accum = Image.new("RGB", image.size, (0, 0, 0))
    black = Image.new("RGB", image.size, (0, 0, 0))

    for name, _, body_cfg, sx, sy, r, color in marker_rows:
        body_glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
        gdraw = ImageDraw.Draw(body_glow, "RGBA")
        glow_brightness = config.BODY_GLOW_BRIGHTNESS.get(name, body_cfg.brightness)
        _draw_single_glow(gdraw, sx, sy, r, color, glow_brightness)
        alpha = body_glow.getchannel("A")
        weighted_glow = Image.composite(body_glow.convert("RGB"), black, alpha)
        glow_accum = ImageChops.add(glow_accum, weighted_glow)

    image.paste(ImageChops.add(image, glow_accum))


def _draw_star(draw: ImageDraw.ImageDraw, sx: float, sy: float, r: float, color: tuple[int, int, int] | int) -> None:
    outer = r
    inner = max(1.0, r * 0.45)

    points = []
    for i in range(10):
        angle = -math.pi / 2.0 + i * (math.pi / 5.0)
        radius = outer if i % 2 == 0 else inner
        points.append((sx + math.cos(angle) * radius, sy + math.sin(angle) * radius))

    draw.polygon(points, fill=color)


def _draw_single_marker(
    draw: ImageDraw.ImageDraw,
    name: str,
    sx: float,
    sy: float,
    r: float,
    color: tuple[int, int, int] | int,
) -> None:
    if name == "earth":
        draw.ellipse((sx - r, sy - r, sx + r, sy + r), fill=color)
    elif name == "sun":
        _draw_star(draw, sx, sy, r, color)
    elif name == "moon":
        draw.polygon([(sx, sy - r), (sx - r, sy + r), (sx + r, sy + r)], fill=color)
    elif dwarf_planet_orbits.is_dwarf_planet_body(name):
        draw.rectangle((sx - r, sy - r, sx + r, sy + r), fill=color)
    else:
        draw.ellipse((sx - r, sy - r, sx + r, sy + r), fill=color)


def _draw_marker_shapes(image: Image.Image, marker_rows: list[MarkerRow]) -> None:
    marker_accum = Image.new("RGB", image.size, (0, 0, 0))
    marker_mask = Image.new("L", image.size, 0)

    for name, _, _, sx, sy, r, color in marker_rows:
        marker_layer = Image.new("RGB", image.size, (0, 0, 0))
        marker_draw = ImageDraw.Draw(marker_layer)
        _draw_single_marker(marker_draw, name, sx, sy, r, color)
        marker_accum = ImageChops.add(marker_accum, marker_layer)

        mask_layer = Image.new("L", image.size, 0)
        mask_draw = ImageDraw.Draw(mask_layer)
        _draw_single_marker(mask_draw, name, sx, sy, r, 255)
        marker_mask = ImageChops.lighter(marker_mask, mask_layer)

    image.paste(marker_accum, mask=marker_mask)


def _compute_label_direction(name: str, body: ProjectedBody, center_name: str) -> tuple[float, float]:
    if name == center_name:
        return 0.0, -1.0

    trail = body.trail_xy
    if len(trail) >= 2:
        x0, y0 = trail[-2]
        x1, y1 = trail[-1]
        vx, vy = x1 - x0, y1 - y0
        mag = math.hypot(vx, vy)
        if mag > 1e-12:
            return vx / mag, vy / mag

    return 1.0, 0.0


def _compute_label_offset(
    dir_x: float,
    dir_y: float,
    label_w: int,
    label_h: int,
    marker_r: float,
    ssaa_scale: int,
) -> float:
    dir_clearance = 0.5 * (abs(dir_x) * label_w + abs(dir_y) * label_h)

    marker_radius_px = marker_r / max(1, ssaa_scale)

    base_gap = (
        math.sqrt(max(1.0, float(marker_radius_px)))
        * ssaa_scale
        * max(0.0, float(config.LABEL_OFFSET_RADIUS_MULTIPLIER))
    )

    edge_padding = max(1.0, 1.5 * ssaa_scale)
    return marker_r + dir_clearance + base_gap + edge_padding


def _draw_single_label(
    draw: ImageDraw.ImageDraw,
    name: str,
    body: ProjectedBody,
    sx: float,
    sy: float,
    r: float,
    color: tuple[int, int, int],
    center_name: str,
    ssaa_scale: int,
) -> None:
    text_scale = max(0.1, float(config.TEXT_SCALE))
    marker_radius_px = r / max(1, ssaa_scale)
    label_radius = math.sqrt(max(1.0, float(marker_radius_px))) * ssaa_scale

    label_size = max(8, int(round(label_radius * 1.8 * text_scale)))
    font = get_label_font(label_size)

    text = name.capitalize()
    dir_x, dir_y = _compute_label_direction(name, body, center_name)

    bbox = draw.textbbox((0, 0), text, font=font)
    label_w, label_h = bbox[2] - bbox[0], bbox[3] - bbox[1]

    offset = _compute_label_offset(dir_x, dir_y, label_w, label_h, r, ssaa_scale)
    anchor_x = sx + dir_x * offset
    anchor_y = sy + dir_y * offset

    draw.text(
        (anchor_x - 0.5 * label_w, anchor_y - 0.5 * label_h),
        text,
        font=font,
        fill=color,
    )


def _draw_labels(image: Image.Image, marker_rows: list[MarkerRow], center_name: str, ssaa_scale: int) -> None:
    if not bool(config.SHOW_BODY_LABELS):
        return

    label_accum = Image.new("RGB", image.size, (0, 0, 0))

    for name, body, _, sx, sy, r, color in marker_rows:
        if name == "sun":
            continue

        label_layer = Image.new("RGB", image.size, (0, 0, 0))
        draw = ImageDraw.Draw(label_layer)
        _draw_single_label(draw, name, body, sx, sy, r, color, center_name, ssaa_scale)
        label_accum = ImageChops.add(label_accum, label_layer)

    image.paste(ImageChops.add(image, label_accum))


def draw_markers(
    image: Image.Image,
    projected: dict[str, ProjectedBody],
    kin_bundle: TrailKinematicsBundle,
    ssaa_scale: int,
) -> None:
    marker_rows = _build_marker_rows(projected, kin_bundle, ssaa_scale)
    center_name = str(config.OBSERVER_CENTER_BODY).strip().lower()

    if bool(config.SHOW_MARKER_GLOW):
        _draw_marker_glow(image, marker_rows)
    _draw_marker_shapes(image, marker_rows)
    _draw_labels(image, marker_rows, center_name, ssaa_scale)
