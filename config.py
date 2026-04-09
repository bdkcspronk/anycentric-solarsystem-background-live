"""Runtime configuration for the wallpaper renderer.

This module intentionally exposes mutable globals because the CLI/runtime wrappers
override settings dynamically before each render.
"""

from dataclasses import dataclass
from pathlib import Path
import math

from config_body_factory import build_all_bodies as _build_bodies_via_factory
from config_selection import (
    evaluate_selection_expression as _evaluate_selection_expression_impl,
    selector_set as _selector_set_impl,
)

@dataclass(frozen=True)
class BodyConfig:
    target: str
    marker_radius_px: int
    brightness: float
    trail_step_minutes: int | None = None


# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent

# Output settings
OUTPUT_PATH = str(PROJECT_ROOT / "wallpaper.png")
IMAGE_WIDTH = 2560
IMAGE_HEIGHT = 1440

# Scene and style settings
# Background brightness (legacy). Keep for backwards compatibility.
BACKGROUND_BRIGHTNESS = 1
# Background color as an RGB tuple (0-255). Can be overridden at runtime.
BACKGROUND_COLOR = (BACKGROUND_BRIGHTNESS, BACKGROUND_BRIGHTNESS, BACKGROUND_BRIGHTNESS)
SUN_RADIUS_PX = 12

# Per-body trail width scale. Actual width uses sqrt(marker_radius_px) * this value.
TRAIL_LINE_WIDTH_PX = 2
TRAIL_MIN_FADE = 0.0
TRAIL_FADE_POWER = 1.0
TRAIL_DYNAMIC_SATURATION = True
# Blend for saturation metric when dynamic saturation is enabled:
# 0.0 uses linear speed, 1.0 uses apparent angular speed.
TRAIL_SATURATION_ANGULAR_BLEND = 0.0
# Blend for brightness metric: 0.0 uses linear speed, 1.0 uses apparent angular speed.
TRAIL_BRIGHTNESS_ANGULAR_BLEND = 0.0

SHOW_BODY_LABELS = False
SHOW_MARKER_GLOW = True
TEXT_SCALE = 3.0
LABEL_OFFSET_RADIUS_MULTIPLIER = 3.0
SHOW_CELESTIAL_SCALE = True

CELESTIAL_SCALE_RADIUS_AU = 8.0
CELESTIAL_SCALE_OPACITY = 0.25
CELESTIAL_SCALE_LINE_WIDTH_PX = 1.25
CELESTIAL_SCALE_XY_COLOR = (120, 180, 255)
CELESTIAL_SCALE_XZ_COLOR = (255, 180, 120)
CELESTIAL_SCALE_YZ_COLOR = (180, 255, 170)
CELESTIAL_SCALE_YZ_YAW_OFFSET_DEG = 0.0

# Anti-aliasing: render at higher resolution then downsample.
SSAA_SCALE = 4

# Projection settings
WORLD_RADIUS_AU = 4.0
WORLD_VIEW_FILL_FRACTION = 0.90
RENDER_INNER_PLANETS_ONLY = False
RENDER_PLANETS_ONLY = False
OBSERVER_CENTER_BODY = "earth"
RENDER_SELECTION_EXPRESSION: str | None = None

# Orthographic view rotation in degrees.
# yaw: rotate around z-axis, pitch: rotate around x-axis, roll: rotate around y-axis
VIEW_YAW_DEG = 0.0
VIEW_PITCH_DEG = 0.0
VIEW_ROLL_DEG = 0.0

# Visual distance remapping controls (projection-only, not ephemeris).
# ORBIT_RADIUS_MODE options: linear, power, sqrt, log
ORBIT_RADIUS_MODE = "log"
ORBIT_RADIUS_POWER = 0.5

# Extra per-body visual distance scaling after projection remap.
# Useful for tiny orbits like the Moon that are otherwise sub-pixel.
BODY_DISTANCE_MULTIPLIERS: dict[str, float] = {
    "moon": 1.0,
    "mercury": 1.0,
    "venus": 1.0,
    "sun": 1.0,
    "earth": 1.0,
    "mars": 1.0,
    "jupiter": 1.0,
    "saturn": 1.0,
    "uranus": 1.0,
    "neptune": 1.0,
    "ceres": 1.0,
    "pluto": 1.0,
    "eris": 1.0,
    "haumea": 1.0,
    "makemake": 1.0,
    "gonggong": 1.0,
    "quaoar": 1.0,
}

# Ephemeris and trail sampling settings
EPHEMERIS_KERNEL = str(PROJECT_ROOT / "de440s.bsp")

TRAIL_STEP_SCALE = 2
TRAIL_BASE_RESOLUTION_FACTOR = 6

def _current_center_solar_year_factor() -> float:
    key = str(OBSERVER_CENTER_BODY).strip().lower()
    return max(1e-6, float(BODY_SOLAR_YEAR_FACTOR.get(key, 1.0)))


def _recompute_trail_timing() -> None:
    global TRAIL_BASE_STEP_MINUTES, TRAIL_DAYS, TRAIL_STEP_MINUTES
    TRAIL_BASE_STEP_MINUTES = 60 * TRAIL_BASE_RESOLUTION_FACTOR
    TRAIL_DAYS = 365.25 * _current_center_solar_year_factor() * TRAIL_STEP_SCALE
    TRAIL_STEP_MINUTES = max(1, int(round(TRAIL_BASE_STEP_MINUTES * TRAIL_STEP_SCALE)))

BODY_MARKER_SCALE = 10
# Marker radius transform factor.
# Effective transform is radius ** (1 / factor) and factor is clamped to >= 0.5.
# - Larger values flatten size differences (approach equal marker sizes).
# - 1.0 keeps linear radii unchanged.
# - 0.5 applies radius ** 2 to increase size separation.
BODY_MARKER_RADIUS_POWER_FACTOR = 5
BODY_MARKER_RADIUS: dict[str, float] = {
    "sun":1,
    "mercury":0.0035,
    "venus":0.0087,
    "earth":0.00917,
    "moon":0.002497,
    "mars":0.00487,
    "jupiter":0.103,
    "saturn":0.087,
    "uranus":0.037,
    "neptune":0.036,
    "ceres": 0.00067,
    "pluto": 0.00171,
    "eris": 0.00172,
    "haumea": 0.00103,
    "makemake": 0.00102,
    "gonggong": 0.00088,
    "quaoar": 0.000798,
}

_marker_radius_factor = max(0.5, float(BODY_MARKER_RADIUS_POWER_FACTOR))
_marker_radius_exp = 1.0 / _marker_radius_factor

BODY_MARKER_RADIUS_PX: dict[str, int] = {
    name: max(0, int((radius ** _marker_radius_exp) * BODY_MARKER_SCALE))
    for name, radius in BODY_MARKER_RADIUS.items()
}

BODY_SOLAR_YEAR_FACTOR: dict[str, float] = {
    "sun": 0.3,
    "moon": 0.97,
    "mercury": 0.24,
    "venus": 0.61,
    "earth": 1,
    "mars": 1.88,
    "jupiter": 11.86,
    "saturn": 29.46,
    "uranus": 84.02,
    "neptune": 164.79,
    "ceres": 4.60,
    "pluto": 247.94,
    "eris": 557.2,
    "haumea": 285.4,
    "makemake": 309.9,
    "gonggong": 554.4,
    "quaoar": 286.8,
}

_recompute_trail_timing()

TRAIL_STEP_BODY_MULTIPLIERS: dict[str, int] = {
    "sun": 1,
    "moon": 1,
    "mercury": 1,
    "venus": 1,
    "earth": 1,
    "mars": 1,
    "jupiter": 4,
    "saturn": 8,
    "uranus": 16,
    "neptune": 32,
    "ceres": 2,
    "pluto": 32,
    "eris": 32,
    "haumea": 32,
    "makemake": 32,
    "gonggong": 32,
    "quaoar": 32,
}

BODY_TARGETS: dict[str, str] = {
    "sun": "sun",
    "moon": "moon",
    "mercury": "mercury",
    "venus": "venus",
    "earth": "earth",
    "mars": "mars barycenter",
    "jupiter": "jupiter barycenter",
    "saturn": "saturn barycenter",
    "uranus": "uranus barycenter",
    "neptune": "neptune barycenter",
    "ceres": "ceres",
    "pluto": "pluto",
    "eris": "eris",
    "haumea": "haumea",
    "makemake": "makemake",
    "gonggong": "gonggong",
    "quaoar": "quaoar",
}

# Per-body glow strength source (0..1). This is intended to use the
# normalized (non-gamma) brightness when available.
BODY_GLOW_BRIGHTNESS: dict[str, float] = {}


def _scaled_trail_step_minutes(multiplier: int) -> int:
    return max(1, int(round(TRAIL_STEP_MINUTES * int(multiplier))))


def _build_all_bodies() -> dict[str, BodyConfig]:
    defaults: dict[str, float] = {
        "sun": 1,
        "moon": 210 / 255.0,
        "mercury": 180 / 255.0,
        "venus": 190 / 255.0,
        "earth": 220 / 255.0,
        "mars": 185 / 255.0,
        "jupiter": 230 / 255.0,
        "saturn": 215 / 255.0,
        "uranus": 200 / 255.0,
        "neptune": 195 / 255.0,
        "ceres": 190 / 255.0,
        "pluto": 205 / 255.0,
        "eris": 210 / 255.0,
        "haumea": 200 / 255.0,
        "makemake": 200 / 255.0,
        "gonggong": 195 / 255.0,
        "quaoar": 190 / 255.0,
    }

    global BODY_GLOW_BRIGHTNESS
    bodies, glow_brightness = _build_bodies_via_factory(
        project_root=PROJECT_ROOT,
        defaults=defaults,
        body_targets=BODY_TARGETS,
        marker_radius_px=BODY_MARKER_RADIUS_PX,
        step_body_multipliers=TRAIL_STEP_BODY_MULTIPLIERS,
        scaled_trail_step_minutes=_scaled_trail_step_minutes,
        body_config_factory=BodyConfig,
    )
    BODY_GLOW_BRIGHTNESS = glow_brightness
    return bodies


# Bodies to include in render order
ALL_BODIES: dict[str, BodyConfig] = _build_all_bodies()

INNER_PLANET_TARGETS = {"mercury", "venus", "earth", "mars"}
PLANET_TARGETS = {"mercury", "venus", "earth", "mars", "jupiter", "saturn", "uranus", "neptune"}
OUTER_PLANET_TARGETS = {"jupiter", "saturn", "uranus", "neptune"}
DWARF_PLANET_TARGETS = {"ceres", "pluto", "eris", "haumea", "makemake", "gonggong", "quaoar"}
MAJOR_PLANET_TARGETS = {"mercury", "venus", "earth", "mars", "jupiter", "saturn", "uranus", "neptune"}
ALL_PLANETS_TARGETS = PLANET_TARGETS | DWARF_PLANET_TARGETS

def _selector_set(key: str) -> set[str]:
    return _selector_set_impl(
        key,
        all_body_keys=set(ALL_BODIES.keys()),
        major_planets=set(MAJOR_PLANET_TARGETS),
        all_planets=set(ALL_PLANETS_TARGETS),
        inner_planets=set(INNER_PLANET_TARGETS),
        outer_planets=set(OUTER_PLANET_TARGETS),
        dwarf_planets=set(DWARF_PLANET_TARGETS),
    )


def _evaluate_selection_expression(expr: str) -> set[str]:
    return _evaluate_selection_expression_impl(
        expr,
        all_body_keys=set(ALL_BODIES.keys()),
        major_planets=set(MAJOR_PLANET_TARGETS),
        all_planets=set(ALL_PLANETS_TARGETS),
        inner_planets=set(INNER_PLANET_TARGETS),
        outer_planets=set(OUTER_PLANET_TARGETS),
        dwarf_planets=set(DWARF_PLANET_TARGETS),
    )


def _select_bodies() -> dict[str, BodyConfig]:
    if RENDER_SELECTION_EXPRESSION:
        selected_names = _evaluate_selection_expression(RENDER_SELECTION_EXPRESSION)
    elif RENDER_PLANETS_ONLY:
        selected_names = set(PLANET_TARGETS)
    elif RENDER_INNER_PLANETS_ONLY:
        selected_names = set(INNER_PLANET_TARGETS)
    else:
        selected_names = set(ALL_BODIES.keys())

    # include the sun always
    selected_names.add("sun")
    # Always include the current center body so relative frame remains valid.
    selected_names.add(str(OBSERVER_CENTER_BODY).strip().lower())
    return {name: body for name, body in ALL_BODIES.items() if name in selected_names}


BODIES: dict[str, BodyConfig] = _select_bodies()

_SELECTION_EXPR_UNSET = object()


def _refresh_selected_bodies() -> None:
    global BODIES
    BODIES = _select_bodies()


def _set_render_mode(
    *,
    inner_planets_only: bool | None = None,
    planets_only: bool | None = None,
    selection_expression: str | None | object = _SELECTION_EXPR_UNSET,
) -> None:
    global RENDER_PLANETS_ONLY, RENDER_INNER_PLANETS_ONLY, RENDER_SELECTION_EXPRESSION

    if inner_planets_only is not None:
        RENDER_INNER_PLANETS_ONLY = bool(inner_planets_only)
        if RENDER_INNER_PLANETS_ONLY:
            RENDER_PLANETS_ONLY = False
            RENDER_SELECTION_EXPRESSION = None

    if planets_only is not None:
        RENDER_PLANETS_ONLY = bool(planets_only)
        if RENDER_PLANETS_ONLY:
            RENDER_INNER_PLANETS_ONLY = False
            RENDER_SELECTION_EXPRESSION = None

    if selection_expression is not _SELECTION_EXPR_UNSET:
        text = None if selection_expression is None else str(selection_expression).strip()
        RENDER_SELECTION_EXPRESSION = text if text else None
        if RENDER_SELECTION_EXPRESSION is not None:
            RENDER_PLANETS_ONLY = False
            RENDER_INNER_PLANETS_ONLY = False

    _refresh_selected_bodies()





def set_render_selection_expression(expr: str | None) -> None:
    _set_render_mode(selection_expression=expr)


def selection_expression_includes_body(expr: str, body_name: str) -> bool:
    key = str(body_name).strip().lower()
    if key not in ALL_BODIES:
        return False
    selected = _evaluate_selection_expression(str(expr))
    return key in selected


def set_observer_center_body(body_name: str) -> None:
    global OBSERVER_CENTER_BODY
    key = str(body_name).strip().lower()
    if key not in ALL_BODIES:
        raise ValueError(f"Unknown center body: {body_name}")
    OBSERVER_CENTER_BODY = key
    _recompute_trail_timing()
    _rebuild_body_configs()


def _rebuild_body_configs() -> None:
    global ALL_BODIES
    ALL_BODIES = _build_all_bodies()
    _refresh_selected_bodies()


def set_trail_sampling(*, scale: float | None = None, base_resolution_factor: float | None = None) -> None:
    global TRAIL_STEP_SCALE, TRAIL_BASE_RESOLUTION_FACTOR
    if scale is not None:
        TRAIL_STEP_SCALE = max(1e-6, float(scale))
    if base_resolution_factor is not None:
        TRAIL_BASE_RESOLUTION_FACTOR = max(1e-6, float(base_resolution_factor))
    _recompute_trail_timing()
    _rebuild_body_configs()


def set_trail_step_scale(scale: float) -> None:
    set_trail_sampling(scale=scale)


def set_trail_base_resolution_factor(factor: float) -> None:
    set_trail_sampling(base_resolution_factor=factor)