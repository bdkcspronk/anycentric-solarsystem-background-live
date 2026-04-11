"""Bottom-right view compass / orbit mode overlay rendering."""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

import config
from render_utils import clamp01, get_label_font


def _rotation_matrix(yaw_deg: float, pitch_deg: float, roll_deg: float) -> tuple[float, float, float, float, float, float, float, float, float]:
    yaw = math.radians(float(yaw_deg))
    pitch = math.radians(float(pitch_deg))
    roll = math.radians(float(roll_deg))

    cy = math.cos(yaw)
    sy = math.sin(yaw)
    cp = math.cos(pitch)
    sp = math.sin(pitch)
    cr = math.cos(roll)
    sr = math.sin(roll)

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


def _fmt_angle(value: float) -> str:
    wrapped_value = ((float(value) + 180.0) % 360.0) - 180.0
    return f"{float(wrapped_value):+.1f}°"


def _orbit_radius_visual_value(value: float) -> float:
    mode = str(config.ORBIT_RADIUS_MODE).strip().lower()
    v = max(0.0, float(value))
    if mode == "power":
        return v ** max(1e-6, float(config.ORBIT_RADIUS_POWER))
    if mode == "sqrt":
        return math.sqrt(v)
    if mode == "log":
        return math.log1p(v)
    return v


def _draw_axis_label(draw: ImageDraw.ImageDraw, x: float, y: float, text: str, font, fill: tuple[int, int, int, int]) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    draw.text((x - 0.5 * w, y - 0.5 * h), text, font=font, fill=fill)


def _draw_compass(draw: ImageDraw.ImageDraw, x: float, y: float, size: float, font) -> None:
    center_x = x + size * 0.5
    center_y = y + size * 0.5
    radius = size * 0.44
    inner_radius = radius * 0.7

    shell_fill = (12, 18, 26, 176)
    shell_outline = (180, 220, 255, 88)
    draw.ellipse(
        (center_x - radius, center_y - radius, center_x + radius, center_y + radius),
        fill=shell_fill,
        outline=shell_outline,
        width=max(1, int(round(size * 0.012))),
    )
    draw.ellipse(
        (center_x - inner_radius, center_y - inner_radius, center_x + inner_radius, center_y + inner_radius),
        outline=(255, 255, 255, 34),
        width=max(1, int(round(size * 0.006))),
    )

    matrix = _rotation_matrix(config.VIEW_YAW_DEG, config.VIEW_PITCH_DEG, config.VIEW_ROLL_DEG)
    axes = (
        ((matrix[0], matrix[3], matrix[6]), (255, 120, 104, 230), "X"),
        ((matrix[1], matrix[4], matrix[7]), (122, 226, 148, 230), "Y"),
        ((matrix[2], matrix[5], matrix[8]), (112, 178, 255, 230), "Z"),
    )

    axis_len = radius * 0.84
    dot_r = max(1.0, size * 0.014)
    cross = radius * 0.12

    draw.line(
        (center_x - cross, center_y, center_x + cross, center_y),
        fill=(255, 255, 255, 50),
        width=max(1, int(round(size * 0.006))),
    )
    draw.line(
        (center_x, center_y - cross, center_x, center_y + cross),
        fill=(255, 255, 255, 50),
        width=max(1, int(round(size * 0.006))),
    )

    for vec, color, label in axes:
        vx, vy, vz = vec
        end_x = center_x + axis_len * float(vx)
        end_y = center_y - axis_len * float(vy)

        depth = 0.45 + 0.55 * clamp01((float(vz) + 1.0) * 0.5)
        rgba = (color[0], color[1], color[2], int(round(color[3] * depth)))
        draw.line((center_x, center_y, end_x, end_y), fill=rgba, width=max(2, int(round(size * 0.018))))
        draw.ellipse(
            (end_x - dot_r, end_y - dot_r, end_x + dot_r, end_y + dot_r),
            fill=rgba,
            outline=(255, 255, 255, 60),
        )
        label_x = center_x + (axis_len + size * 0.08) * float(vx)
        label_y = center_y - (axis_len + size * 0.08) * float(vy)
        _draw_axis_label(draw, label_x, label_y, label, font, rgba)


def _draw_ruler(draw: ImageDraw.ImageDraw, x: float, y: float, width: float, font) -> None:
    start_x = x
    end_x = x + width
    center_y = y + 0.5 * (font.size if hasattr(font, "size") else 12)
    line_y = center_y
    major_h = max(8.0, width * 0.03)
    minor_h = major_h * 0.58
    line_color = (208, 224, 240, 206)
    tick_color = (196, 214, 232, 220)

    draw.line((start_x, line_y, end_x, line_y), fill=line_color, width=max(1, int(round(width * 0.008))))

    min_au = 0.0
    max_au = 10.0
    min_visual = _orbit_radius_visual_value(min_au)
    max_visual = _orbit_radius_visual_value(max_au)
    visual_span = max(1e-12, max_visual - min_visual)

    tick_count = 10
    for i in range(tick_count + 1):
        au = float(i)
        visual_value = _orbit_radius_visual_value(au)
        t = (visual_value - min_visual) / visual_span
        tick_x = start_x + width * t
        is_major = i in {0, 5, 10}
        tick_top = line_y - (major_h if is_major else minor_h)
        draw.line((tick_x, line_y, tick_x, tick_top), fill=tick_color, width=max(1, int(round(width * 0.003))))

        if is_major:
            label = f"{i}"
            bbox = draw.textbbox((0, 0), label, font=font)
            label_w = bbox[2] - bbox[0]
            label_h = bbox[3] - bbox[1]
            draw.text((tick_x - 0.5 * label_w, line_y + major_h * 0.18), label, font=font, fill=tick_color)


def draw_view_overlay(image: Image.Image) -> None:
    render_width, render_height = image.size
    ssaa_scale = max(1, int(config.SSAA_SCALE))

    overlay = Image.new("RGBA", (render_width, render_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    pad = int(round(20 * ssaa_scale))
    panel_w = int(round(350 * ssaa_scale))
    panel_h = int(round(200 * ssaa_scale))
    left = render_width - pad - panel_w
    top = render_height - pad - panel_h

    background = (8, 12, 18, 168)
    outline = (160, 200, 235, 70)
    draw.rounded_rectangle(
        (left, top, left + panel_w, top + panel_h),
        radius=int(round(18 * ssaa_scale)),
        fill=background,
        outline=outline,
        width=max(1, int(round(1.5 * ssaa_scale))),
    )

    title_font = get_label_font(int(round(11 * ssaa_scale)))
    body_font = get_label_font(int(round(10 * ssaa_scale)))
    small_font = get_label_font(int(round(9 * ssaa_scale)))

    inner_pad = int(round(10 * ssaa_scale))
    content_left = left + inner_pad
    content_top = top + inner_pad
    content_w = max(1.0, float(panel_w - 2 * inner_pad))
    content_h = max(1.0, float(panel_h - 2 * inner_pad))

    title_ratio = max(1e-6, float(getattr(config, "ORIENTATION_OVERLAY_TITLE_HEIGHT_RATIO", 0.18)))
    gimbal_ratio = max(1e-6, float(getattr(config, "ORIENTATION_OVERLAY_GIMBAL_HEIGHT_RATIO", 0.58)))
    ruler_ratio = max(1e-6, float(getattr(config, "ORIENTATION_OVERLAY_RULER_HEIGHT_RATIO", 0.24)))
    ratio_sum = title_ratio + gimbal_ratio + ruler_ratio

    title_h = content_h * (title_ratio / ratio_sum)
    gimbal_h = content_h * (gimbal_ratio / ratio_sum)
    ruler_h = content_h * (ruler_ratio / ratio_sum)

    title_x = content_left
    title_y = content_top + max(0.0, 0.12 * title_h)
    draw.text((title_x, title_y), "VIEW", font=title_font, fill=(232, 240, 248, 230))

    gimbal_top = content_top + title_h
    compass_size = min(
        int(round(86 * ssaa_scale)),
        max(1, int(round(gimbal_h * 0.92))),
    )
    compass_x = content_left
    compass_y = int(round(gimbal_top + max(0.0, 0.04 * gimbal_h)))
    _draw_compass(draw, compass_x, compass_y, compass_size, body_font)

    text_x = compass_x + compass_size + int(round(12 * ssaa_scale))
    text_y = int(round(gimbal_top + max(0.0, 0.08 * gimbal_h)))
    line_gap = max(1, int(round(min(14 * ssaa_scale, gimbal_h / 3.8))))
    text_color = (228, 236, 244, 220)

    lines = (
        ("yaw", _fmt_angle(config.VIEW_YAW_DEG)),
        ("pitch", _fmt_angle(config.VIEW_PITCH_DEG)),
        ("roll", _fmt_angle(config.VIEW_ROLL_DEG)),
    )
    for idx, (label, value) in enumerate(lines):
        draw.text(
            (text_x, text_y + idx * line_gap),
            f"{label:<6}{value:>9}",
            font=body_font,
            fill=text_color,
        )

    ruler_top = gimbal_top + gimbal_h
    ruler_x = content_left
    ruler_w = content_w
    ruler_y = int(round(ruler_top + max(0.0, 0.06 * ruler_h)))
    _draw_ruler(draw, ruler_x, ruler_y, ruler_w, small_font)
    
    composited = Image.alpha_composite(image.convert("RGBA"), overlay)
    image.paste(composited.convert("RGB"))
