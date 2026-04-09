"""Celestial scale overlay rendering."""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

import config
from projection import ProjectedBody
from render_utils import clamp01


def _to_visual_xy_au_for_scale(
    x_au: float,
    y_au: float,
    z_au: float,
    yaw_offset_deg: float = 0.0,
) -> tuple[float, float]:
    yaw = math.radians(config.VIEW_YAW_DEG + yaw_offset_deg)
    pitch = math.radians(config.VIEW_PITCH_DEG)
    roll = math.radians(config.VIEW_ROLL_DEG)

    cy = math.cos(yaw)
    sy = math.sin(yaw)
    x_au, y_au = (cy * x_au - sy * y_au, sy * x_au + cy * y_au)

    cp = math.cos(pitch)
    sp = math.sin(pitch)
    y_au, z_au = (cp * y_au - sp * z_au, sp * y_au + cp * z_au)

    cr = math.cos(roll)
    sr = math.sin(roll)
    x_au, z_au = (cr * x_au + sr * z_au, -sr * x_au + cr * z_au)

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

        stretch = visual_r / r
        x_au *= stretch
        y_au *= stretch

    return (x_au, y_au)


def _infer_projection_scale(projected: dict[str, ProjectedBody]) -> float:
    half_w = config.IMAGE_WIDTH * 0.5
    half_h = config.IMAGE_HEIGHT * 0.5
    samples: list[float] = []

    for name in config.BODIES:
        body = projected.get(name)
        if body is None:
            continue

        x_au, y_au, z_au = body.position_au
        vx, vy = _to_visual_xy_au_for_scale(x_au, y_au, z_au)
        x_px, y_px = body.position_xy

        if abs(vx) > 1e-10:
            s = (x_px - half_w) / vx
            if math.isfinite(s) and s > 0.0:
                samples.append(s)
        if abs(vy) > 1e-10:
            s = (half_h - y_px) / vy
            if math.isfinite(s) and s > 0.0:
                samples.append(s)

    if samples:
        samples.sort()
        return samples[len(samples) // 2]

    fallback_radius = max(1e-12, float(config.WORLD_RADIUS_AU))
    return min(config.IMAGE_WIDTH, config.IMAGE_HEIGHT) * 0.5 / fallback_radius


def draw_celestial_scale_overlay(
    image: Image.Image,
    projected: dict[str, ProjectedBody],
    ssaa_scale: int,
) -> None:
    if not bool(config.SHOW_CELESTIAL_SCALE):
        return

    radius_au = max(1e-6, float(config.CELESTIAL_SCALE_RADIUS_AU))
    opacity = clamp01(float(config.CELESTIAL_SCALE_OPACITY))
    if opacity <= 0.0:
        return

    render_width, render_height = image.size
    half_w = render_width * 0.5
    half_h = render_height * 0.5
    line_w = max(1, int(round(float(config.CELESTIAL_SCALE_LINE_WIDTH_PX) * ssaa_scale)))
    alpha = int(round(opacity * 255.0))

    scale = _infer_projection_scale(projected) * ssaa_scale
    samples = 720

    xy_color = tuple(int(max(0, min(255, c))) for c in config.CELESTIAL_SCALE_XY_COLOR)
    xz_color = tuple(int(max(0, min(255, c))) for c in config.CELESTIAL_SCALE_XZ_COLOR)
    yz_color = tuple(int(max(0, min(255, c))) for c in config.CELESTIAL_SCALE_YZ_COLOR)
    yz_yaw_offset_deg = float(config.CELESTIAL_SCALE_YZ_YAW_OFFSET_DEG)

    xy_points: list[tuple[float, float]] = []
    xz_points: list[tuple[float, float]] = []
    yz_points: list[tuple[float, float]] = []
    for i in range(samples + 1):
        t = (2.0 * math.pi * i) / samples

        x1 = radius_au * math.cos(t)
        y1 = radius_au * math.sin(t)
        z1 = 0.0
        vx1, vy1 = _to_visual_xy_au_for_scale(x1, y1, z1)
        xy_points.append((half_w + vx1 * scale, half_h - vy1 * scale))

        x2 = radius_au * math.cos(t)
        y2 = 0.0
        z2 = radius_au * math.sin(t)
        vx2, vy2 = _to_visual_xy_au_for_scale(x2, y2, z2)
        xz_points.append((half_w + vx2 * scale, half_h - vy2 * scale))

        x3 = 0.0
        y3 = radius_au * math.cos(t)
        z3 = radius_au * math.sin(t)
        vx3, vy3 = _to_visual_xy_au_for_scale(x3, y3, z3, yaw_offset_deg=yz_yaw_offset_deg)
        yz_points.append((half_w + vx3 * scale, half_h - vy3 * scale))

    overlay = Image.new("RGBA", (render_width, render_height), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    d.line(xy_points, fill=(xy_color[0], xy_color[1], xy_color[2], alpha), width=line_w)
    d.line(xz_points, fill=(xz_color[0], xz_color[1], xz_color[2], alpha), width=line_w)
    d.line(yz_points, fill=(yz_color[0], yz_color[1], yz_color[2], alpha), width=line_w)

    composited = Image.alpha_composite(image.convert("RGBA"), overlay)
    image.paste(composited.convert("RGB"))
