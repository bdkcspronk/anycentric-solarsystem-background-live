"""Body-config construction helpers."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def load_body_brightness_map(project_root: Path, defaults: dict[str, float]) -> dict[str, float]:
    bp_path = project_root / "brightness_values.json"
    if not bp_path.exists():
        return {}

    try:
        with open(bp_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}

    brightness_map: dict[str, float] = {}
    for name, payload in data.items():
        if name not in defaults or not isinstance(payload, dict) or name.startswith("__"):
            continue

        val = payload.get("brightness_final")
        if isinstance(val, (int, float)) and math.isfinite(val):
            brightness_map[name] = _clamp01(float(val))

    return brightness_map


def body_brightness_lookup(project_root: Path, defaults: dict[str, float]) -> dict[str, float]:
    loaded = load_body_brightness_map(project_root, defaults)
    return {key: loaded.get(key, _clamp01(defaults.get(key, 0.5))) for key in defaults}


def build_all_bodies(
    *,
    project_root: Path,
    defaults: dict[str, float],
    body_targets: dict[str, str],
    marker_radius_px: dict[str, int],
    trail_step_minutes_by_body: dict[str, int],
    body_config_factory: Callable[..., Any],
) -> tuple[dict[str, Any], dict[str, float]]:
    brightness_lookup = body_brightness_lookup(project_root, defaults)

    def brightness_for(name: str) -> float:
        return brightness_lookup.get(name, _clamp01(defaults.get(name, 0.5)))

    glow_brightness = {name: brightness_for(name) for name in defaults.keys()}

    bodies = {
        key: body_config_factory(
            target,
            marker_radius_px=marker_radius_px[key],
            brightness=brightness_for(key),
            trail_step_minutes=int(trail_step_minutes_by_body[key]),
        )
        for key, target in body_targets.items()
    }

    return bodies, glow_brightness
