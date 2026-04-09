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
