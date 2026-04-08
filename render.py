from __future__ import annotations

import colorsys
from datetime import datetime
from functools import lru_cache
import hashlib
import json
import math
import os
import time

from PIL import Image, ImageChops, ImageDraw, ImageFont

import config
import dwarf_planet_orbits
from projection import ProjectedBody
from trail_kinematics import TrailKinematicsBundle, compute_or_load_kinematics


TRAIL_LAYER_CACHE_IMAGE = "trail_layer_cache.png"
TRAIL_LAYER_CACHE_META = "trail_layer_cache.json"
OVERLAY_STATE_FILE = "render_overlay_state.json"
MARKER_STYLE_VERSION = 4


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _revalue_rgb(color: tuple[int, int, int], target_value_255: int) -> tuple[int, int, int]:
    r, g, b = color
    h, s, _ = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    target_v = _clamp01(target_value_255 / 255.0)
    rr, gg, bb = colorsys.hsv_to_rgb(h, s, target_v)
    return (int(round(rr * 255.0)), int(round(gg * 255.0)), int(round(bb * 255.0)))


@lru_cache(maxsize=32)
def _get_label_font(size_px: int) -> ImageFont.ImageFont:
    size = max(8, int(size_px))
    for font_name in ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(font_name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _trail_cache_paths() -> tuple[str, str]:
    base = os.path.dirname(__file__)
    return (
        os.path.join(base, TRAIL_LAYER_CACHE_IMAGE),
        os.path.join(base, TRAIL_LAYER_CACHE_META),
    )


def _overlay_state_path() -> str:
    return os.path.join(os.path.dirname(__file__), OVERLAY_STATE_FILE)


def _overlay_signature() -> str:
    payload = {
        "marker_style_version": MARKER_STYLE_VERSION,
        "image_width": config.IMAGE_WIDTH,
        "image_height": config.IMAGE_HEIGHT,
        "ssaa": config.SSAA_SCALE,
        "background": config.BACKGROUND_BRIGHTNESS,
        "trail_line_width": config.TRAIL_LINE_WIDTH_PX,
        "trail_base_brightness": config.TRAIL_BASE_BRIGHTNESS,
        "trail_dynamic_saturation": bool(config.TRAIL_DYNAMIC_SATURATION),
        "trail_saturation_angular_blend": config.TRAIL_SATURATION_ANGULAR_BLEND,
        "trail_brightness_angular_blend": config.TRAIL_BRIGHTNESS_ANGULAR_BLEND,
        "trail_min_fade": config.TRAIL_MIN_FADE,
        "trail_fade_power": config.TRAIL_FADE_POWER,
        "view_yaw": config.VIEW_YAW_DEG,
        "view_pitch": config.VIEW_PITCH_DEG,
        "view_roll": config.VIEW_ROLL_DEG,
        "orbit_radius_mode": config.ORBIT_RADIUS_MODE,
        "orbit_radius_power": config.ORBIT_RADIUS_POWER,
        "world_view_fill_fraction": config.WORLD_VIEW_FILL_FRACTION,
        "show_labels": config.SHOW_BODY_LABELS,
        "text_scale": config.TEXT_SCALE,
        "label_offset_mul": config.LABEL_OFFSET_RADIUS_MULTIPLIER,
        "show_celestial_scale": bool(config.SHOW_CELESTIAL_SCALE),
        "celestial_scale_radius_au": float(config.CELESTIAL_SCALE_RADIUS_AU),
        "celestial_scale_opacity": float(config.CELESTIAL_SCALE_OPACITY),
        "celestial_scale_line_width_px": float(config.CELESTIAL_SCALE_LINE_WIDTH_PX),
        "celestial_scale_xy_color": tuple(config.CELESTIAL_SCALE_XY_COLOR),
        "celestial_scale_xz_color": tuple(config.CELESTIAL_SCALE_XZ_COLOR),
        "celestial_scale_yz_color": tuple(config.CELESTIAL_SCALE_YZ_COLOR),
        "celestial_scale_yz_yaw_offset_deg": float(config.CELESTIAL_SCALE_YZ_YAW_OFFSET_DEG),
        "body_distance_multipliers": config.BODY_DISTANCE_MULTIPLIERS,
        "bodies": {
            name: {
                "radius": body_cfg.marker_radius_px,
                "brightness": body_cfg.brightness,
            }
            for name, body_cfg in config.BODIES.items()
        },
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def is_overlay_update_due() -> bool:
    path = _overlay_state_path()
    sig = _overlay_signature()
    if not os.path.exists(path):
        return True
    try:
        with open(path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, json.JSONDecodeError):
        return True
    return meta.get("signature") != sig


def _mark_overlay_rendered() -> None:
    path = _overlay_state_path()
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"signature": _overlay_signature()}, f)
    os.replace(tmp, path)


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
        "trail_base_brightness": config.TRAIL_BASE_BRIGHTNESS,
        "trail_brightness_angular_blend": config.TRAIL_BRIGHTNESS_ANGULAR_BLEND,
        "trail_min_fade": config.TRAIL_MIN_FADE,
        "trail_fade_power": config.TRAIL_FADE_POWER,
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

    # On Windows, files can be transiently locked by another process/read handle.
    # Retry replaces briefly instead of failing the render.
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

        body_layer = Image.new("RGB", (render_width, render_height), (0, 0, 0))
        d = ImageDraw.Draw(body_layer)
        for i in range(len(trail_xy) - 1):
            p0 = trail_xy[i]
            p1 = trail_xy[i + 1]
            d.line(
                (p0[0] * ssaa_scale, p0[1] * ssaa_scale, p1[0] * ssaa_scale, p1[1] * ssaa_scale),
                fill=colors[i],
                width=line_width,
            )
        trail_image = ImageChops.add(trail_image, body_layer)

    return trail_image


def _get_trail_layer_image(
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
        # Cache write is optional; never fail wallpaper generation on cache I/O issues.
        pass
    return trail_image


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
        if body is None or not body.trail_au:
            continue

        x_au, y_au, z_au = body.trail_au[-1]
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


def _draw_celestial_scale_overlay(
    image: Image.Image,
    projected: dict[str, ProjectedBody],
    ssaa_scale: int,
) -> None:
    if not bool(config.SHOW_CELESTIAL_SCALE):
        return

    radius_au = max(1e-6, float(config.CELESTIAL_SCALE_RADIUS_AU))
    opacity = _clamp01(float(config.CELESTIAL_SCALE_OPACITY))
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


def _draw_markers(
    image: Image.Image,
    projected: dict[str, ProjectedBody],
    kin_bundle: TrailKinematicsBundle,
    ssaa_scale: int,
) -> None:
    draw = ImageDraw.Draw(image)
    center_name = str(config.OBSERVER_CENTER_BODY).strip().lower()

    for name, body_cfg in config.BODIES.items():
        body = projected[name]
        x, y = body.position_xy
        sx = x * ssaa_scale
        sy = y * ssaa_scale
        r = body_cfg.marker_radius_px * ssaa_scale

        if name == center_name:
            marker_color = (255, 255, 255)
        else:
            body_kin = kin_bundle.by_body.get(name)
            if body_kin is not None and body_kin.segment_colors:
                marker_color = _revalue_rgb(body_kin.segment_colors[-1], body_cfg.brightness)
            else:
                b = body_cfg.brightness
                marker_color = (b, b, b)

        body_kin = kin_bundle.by_body.get(name)

        if name == "earth":
            draw.ellipse((sx - r, sy - r, sx + r, sy + r), fill=marker_color)
        elif name == "sun":
            outer = r
            inner = max(1.0, r * 0.45)
            points: list[tuple[float, float]] = []
            for i in range(10):
                angle = -math.pi / 2.0 + i * (math.pi / 5.0)
                radius = outer if i % 2 == 0 else inner
                points.append((sx + math.cos(angle) * radius, sy + math.sin(angle) * radius))
            draw.polygon(points, fill=marker_color)
        elif name == "moon":
            points = [
                (sx, sy - r),
                (sx - r, sy + r),
                (sx + r, sy + r),
            ]
            draw.polygon(points, fill=marker_color)
        elif dwarf_planet_orbits.is_dwarf_planet_body(name):
            draw.rectangle((sx - r, sy - r, sx + r, sy + r), fill=marker_color)
        else:
            draw.ellipse((sx - r, sy - r, sx + r, sy + r), fill=marker_color)

        if not bool(config.SHOW_BODY_LABELS):
            continue

        if name == "sun":
            continue

        text_scale = max(0.1, float(config.TEXT_SCALE))
        label_radius = math.sqrt(max(1.0, float(body_cfg.marker_radius_px))) * ssaa_scale
        label_size = max(8, int(round(label_radius * 1.8 * text_scale)))
        font = _get_label_font(label_size)
        label_text = name.capitalize()

        if name == center_name:
            # Keep the observer-center label fixed above the body.
            dir_x, dir_y = 0.0, -1.0
        else:
            # Follow the latest projected trail tangent (center-frame relative velocity).
            trail_xy = body.trail_xy
            if len(trail_xy) >= 2:
                x_prev, y_prev = trail_xy[-2]
                x_last, y_last = trail_xy[-1]
                vx = x_last - x_prev
                vy = y_last - y_prev
                vm = math.hypot(vx, vy)
                if vm > 1e-12:
                    dir_x, dir_y = vx / vm, vy / vm
                else:
                    dir_x, dir_y = 1.0, 0.0
            else:
                dir_x, dir_y = 1.0, 0.0

        offset = label_radius
        anchor_x = sx + dir_x * offset
        anchor_y = sy + dir_y * offset

        bbox = draw.textbbox((0, 0), label_text, font=font)
        label_w = bbox[2] - bbox[0]
        label_h = bbox[3] - bbox[1]
        marker_r = max(0.0, float(body_cfg.marker_radius_px) * ssaa_scale)

        # Robust clearance: keep text box outside marker by projecting text half-extents
        # onto placement direction. Horizontal placement pushes farther than vertical.
        dir_clearance = 0.5 * (abs(dir_x) * label_w + abs(dir_y) * label_h)
        base_gap = label_radius * max(0.0, float(config.LABEL_OFFSET_RADIUS_MULTIPLIER))
        edge_padding = max(1.0, 1.5 * ssaa_scale)
        offset = marker_r + dir_clearance + base_gap + edge_padding

        anchor_x = sx + dir_x * offset
        anchor_y = sy + dir_y * offset
        draw.text((anchor_x - 0.5 * label_w, anchor_y - 0.5 * label_h), label_text, font=font, fill=marker_color)


def render_wallpaper(projected: dict[str, ProjectedBody], at_time: datetime) -> Image.Image:
    del at_time

    ssaa_scale = max(1, int(config.SSAA_SCALE))
    render_width = config.IMAGE_WIDTH * ssaa_scale
    render_height = config.IMAGE_HEIGHT * ssaa_scale

    image = Image.new("RGB", (render_width, render_height), (config.BACKGROUND_BRIGHTNESS,) * 3)
    kin_bundle = compute_or_load_kinematics(projected)
    trail_image = _get_trail_layer_image(projected, kin_bundle, render_width, render_height, ssaa_scale)
    image = ImageChops.add(image, trail_image)
    _draw_celestial_scale_overlay(image, projected, ssaa_scale)
    _draw_markers(image, projected, kin_bundle, ssaa_scale)

    if ssaa_scale > 1:
        image = image.resize((config.IMAGE_WIDTH, config.IMAGE_HEIGHT), resample=Image.Resampling.LANCZOS)

    image.save(config.OUTPUT_PATH, format="PNG")
    _mark_overlay_rendered()
    return image
