"""High-resolution trail/marker renderer with layered caching."""

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
MARKER_STYLE_VERSION = 8


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _revalue_rgb(color: tuple[int, int, int], target_value: float | int | None) -> tuple[int, int, int]:
    """Revalue an RGB color to a target V (0..1 float or 0..255 int).

    Accepts `target_value` as:
    - float in 0..1: used directly as HSV V
    - int in 0..255: converted to 0..1
    - None: treated as 1.0
    """
    r, g, b = color
    h, s, _ = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    if target_value is None:
        target_v = 1.0
    elif isinstance(target_value, (int,)):
        target_v = _clamp01(float(target_value) / 255.0)
    else:
        target_v = _clamp01(float(target_value))
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
        "show_glow": bool(config.SHOW_MARKER_GLOW),
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

        # Bridge the gap from the last step-aligned trail sample to the exact
        # current marker position.
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
        return _revalue_rgb(body_kin.segment_colors[idx], body_cfg.brightness)

    bv = int(round(_clamp01(float(body_cfg.brightness)) * 255.0))
    return (bv, bv, bv)

def _build_marker_rows(
    projected: dict[str, ProjectedBody],
    kin_bundle: TrailKinematicsBundle,
    ssaa_scale: int,
) -> list[tuple[str, ProjectedBody, config.BodyConfig, float, float, float, tuple[int, int, int]]]:
    rows = []
    center_name = str(config.OBSERVER_CENTER_BODY).strip().lower()

    for name, body_cfg in config.BODIES.items():
        body = projected[name]
        sx, sy = _scale_position(body.position_xy, ssaa_scale)
        r = body_cfg.marker_radius_px * ssaa_scale
        color = _resolve_marker_color(name, body_cfg, kin_bundle, center_name)

        rows.append((name, body, body_cfg, sx, sy, r, color))

    return rows

def _draw_single_glow(gdraw, sx, sy, r, color, brightness: float) -> None:
    b = _clamp01(float(brightness))
    if b <= 0.0:
        return

    glow_strength = b ** 2.0
    if glow_strength <= 1e-6:
        return

    # Keep a small floor so tiny markers can still glow, but avoid flattening
    # all bodies into the same giant halo footprint.
    base_r = max(24.0, 5 * float(r))
    inner_r = base_r
    outer_r = base_r * (1.6 + 2.2 * glow_strength)

    peak_alpha = int(round(88.0 * glow_strength))
    peak_alpha = max(0, min(128, peak_alpha))

    rings = 4

    # IMPORTANT: outer → inner
    for i in range(rings, 0, -1):
        t = i / float(rings)  # 1 → outer, 0 → inner

        rr = outer_r * t

        inner_weight = 1.0 - t
        alpha = int(round(peak_alpha * (0.8 * (inner_weight ** 1.7))))

        if alpha <= 0:
            continue

        gdraw.ellipse(
            (sx - rr, sy - rr, sx + rr, sy + rr),
            fill=(*color, max(0, min(255, alpha))),
        )

def _draw_marker_glow(
    image: Image.Image,
    marker_rows,
) -> None:
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

def _draw_star(draw, sx, sy, r, color) -> None:
    outer = r
    inner = max(1.0, r * 0.45)

    points = []
    for i in range(10):
        angle = -math.pi / 2.0 + i * (math.pi / 5.0)
        radius = outer if i % 2 == 0 else inner
        points.append((sx + math.cos(angle) * radius, sy + math.sin(angle) * radius))

    draw.polygon(points, fill=color)

def _draw_single_marker(draw, name: str, sx, sy, r, color) -> None:
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

def _draw_marker_shapes(image: Image.Image, marker_rows, kin_bundle) -> None:
    del kin_bundle
    marker_accum = Image.new("RGB", image.size, (0, 0, 0))
    marker_mask = Image.new("L", image.size, 0)

    for name, body, body_cfg, sx, sy, r, color in marker_rows:
        del body, body_cfg
        marker_layer = Image.new("RGB", image.size, (0, 0, 0))
        marker_draw = ImageDraw.Draw(marker_layer)
        _draw_single_marker(marker_draw, name, sx, sy, r, color)
        marker_accum = ImageChops.add(marker_accum, marker_layer)

        mask_layer = Image.new("L", image.size, 0)
        mask_draw = ImageDraw.Draw(mask_layer)
        _draw_single_marker(mask_draw, name, sx, sy, r, 255)
        marker_mask = ImageChops.lighter(marker_mask, mask_layer)

    image.paste(marker_accum, mask=marker_mask)

def _save_output_image(image: Image.Image, output_path: str) -> None:
    """Save output image atomically with short retry windows for Windows locks."""

    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    unique = f"{os.getpid()}_{int(time.time() * 1000)}"
    tmp_path = f"{output_path}.{unique}.tmp"
    image.save(tmp_path, format="PNG")

    delays = (0.02, 0.05, 0.1, 0.2, 0.4)
    last_err: OSError | None = None
    for delay in delays:
        try:
            os.replace(tmp_path, output_path)
            last_err = None
            break
        except OSError as e:
            last_err = e
            time.sleep(delay)

    if last_err is not None:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        raise last_err

def _compute_label_direction(name, body, center_name):
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

def _compute_label_offset(dir_x, dir_y, label_w, label_h, body_cfg, marker_r, ssaa_scale):
    dir_clearance = 0.5 * (abs(dir_x) * label_w + abs(dir_y) * label_h)

    base_gap = (
        math.sqrt(max(1.0, float(body_cfg.marker_radius_px)))
        * ssaa_scale
        * max(0.0, float(config.LABEL_OFFSET_RADIUS_MULTIPLIER))
    )

    edge_padding = max(1.0, 1.5 * ssaa_scale)

    return marker_r + dir_clearance + base_gap + edge_padding


def _draw_single_label(draw, name, body, body_cfg, sx, sy, r, color, center_name, ssaa_scale):
    text_scale = max(0.1, float(config.TEXT_SCALE))

    label_radius = (
        math.sqrt(max(1.0, float(body_cfg.marker_radius_px))) * ssaa_scale
    )

    label_size = max(8, int(round(label_radius * 1.8 * text_scale)))
    font = _get_label_font(label_size)

    text = name.capitalize()
    dir_x, dir_y = _compute_label_direction(name, body, center_name)

    bbox = draw.textbbox((0, 0), text, font=font)
    label_w, label_h = bbox[2] - bbox[0], bbox[3] - bbox[1]

    offset = _compute_label_offset(
        dir_x, dir_y, label_w, label_h, body_cfg, r, ssaa_scale
    )

    anchor_x = sx + dir_x * offset
    anchor_y = sy + dir_y * offset

    draw.text(
        (anchor_x - 0.5 * label_w, anchor_y - 0.5 * label_h),
        text,
        font=font,
        fill=color,
    )

def _draw_labels(image, marker_rows, center_name, ssaa_scale):
    if not bool(config.SHOW_BODY_LABELS):
        return

    label_accum = Image.new("RGB", image.size, (0, 0, 0))

    for name, body, body_cfg, sx, sy, r, color in marker_rows:
        if name == "sun":
            continue

        label_layer = Image.new("RGB", image.size, (0, 0, 0))
        draw = ImageDraw.Draw(label_layer)
        _draw_single_label(
            draw, name, body, body_cfg, sx, sy, r, color, center_name, ssaa_scale
        )

        label_accum = ImageChops.add(label_accum, label_layer)

    image.paste(ImageChops.add(image, label_accum))

def _draw_markers(image, projected, kin_bundle, ssaa_scale):
    marker_rows = _build_marker_rows(projected, kin_bundle, ssaa_scale)
    center_name = str(config.OBSERVER_CENTER_BODY).strip().lower()

    if bool(config.SHOW_MARKER_GLOW):
        _draw_marker_glow(image, marker_rows)
    _draw_marker_shapes(image, marker_rows, kin_bundle)
    _draw_labels(image, marker_rows, center_name, ssaa_scale)

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

    _save_output_image(image, config.OUTPUT_PATH)
    _mark_overlay_rendered()
    return image
