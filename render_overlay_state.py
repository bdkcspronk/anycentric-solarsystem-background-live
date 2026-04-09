"""Overlay state signature and persistence helpers."""

from __future__ import annotations

import hashlib
import json
import os

import config


OVERLAY_STATE_FILE = "render_overlay_state.json"
MARKER_STYLE_VERSION = 8


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


def mark_overlay_rendered() -> None:
    path = _overlay_state_path()
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"signature": _overlay_signature()}, f)
    os.replace(tmp, path)
