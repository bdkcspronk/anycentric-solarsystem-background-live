"""CLI entrypoint for rendering the wallpaper once."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import os

import config
import ephemeris
import projection
import render


@dataclass(frozen=True)
class RunOptions:
    show_labels: bool = False
    glow_enabled: bool = True
    image_width: int = 2560
    image_height: int = 1440
    yaw_deg: float = 0.0
    pitch_deg: float = 70.0
    roll_deg: float = 0.0
    ssaa_scale: int = 4
    celestial_scale_enabled: bool | None = None
    dynamic_saturation: bool | None = None
    saturation_angular_blend: float | None = None
    brightness_angular_blend: float | None = None
    trail_base_resolution_factor: float | None = None
    trail_step_scale: float | None = None
    orbit_radius_mode: str | None = None
    orbit_radius_power: float | None = None
    marker_size_mode: str | None = None
    marker_gamma: float | None = None
    center_body: str | None = None
    selection_expression: str | None = None
    bg_color: tuple[int, int, int] | None = None


def _parse_bool(value: str) -> bool:
    v = str(value).strip().lower()
    if v in {"true", "1", "yes", "y", "on"}:
        return True
    if v in {"false", "0", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError("Expected True or False")


def _parse_color(value: str) -> tuple[int, int, int]:
    """Parse a color name or 6-digit hex string into an RGB tuple.

    Accepts names: black, white, red, green, blue, orange, grey/gray.
    Accepts hex like '#ff00ff' or 'ff00ff'.
    """
    if value is None:
        raise argparse.ArgumentTypeError("Color value cannot be None")
    v = str(value).strip().lower()
    named = {
        "black": (0, 0, 0),
        "white": (255, 255, 255),
        "red": (255, 0, 0),
        "green": (0, 255, 0),
        "blue": (0, 0, 255),
        "orange": (255, 165, 0),
        "grey": (128, 128, 128),
        "gray": (128, 128, 128),
    }
    if v in named:
        return named[v]
    if v.startswith("#"):
        v = v[1:]
    if len(v) == 6 and all(c in "0123456789abcdef" for c in v):
        try:
            r = int(v[0:2], 16)
            g = int(v[2:4], 16)
            b = int(v[4:6], 16)
            return (r, g, b)
        except ValueError:
            pass
    raise argparse.ArgumentTypeError("Expected color name or 6-digit hex (e.g. '#ff00ff')")


def _apply_runtime_config(options: RunOptions) -> None:
    config.SHOW_BODY_LABELS = bool(options.show_labels)
    config.SHOW_MARKER_GLOW = bool(options.glow_enabled)
    config.IMAGE_WIDTH = max(1, int(options.image_width))
    config.IMAGE_HEIGHT = max(1, int(options.image_height))
    config.VIEW_YAW_DEG = float(options.yaw_deg)
    config.VIEW_PITCH_DEG = float(options.pitch_deg)
    config.VIEW_ROLL_DEG = float(options.roll_deg)
    config.SSAA_SCALE = max(1, int(options.ssaa_scale))
    if options.celestial_scale_enabled is not None:
        config.SHOW_CELESTIAL_SCALE = bool(options.celestial_scale_enabled)
    if options.dynamic_saturation is not None:
        config.TRAIL_DYNAMIC_SATURATION = bool(options.dynamic_saturation)
    if options.saturation_angular_blend is not None:
        config.TRAIL_SATURATION_ANGULAR_BLEND = float(options.saturation_angular_blend)
    if options.brightness_angular_blend is not None:
        config.TRAIL_BRIGHTNESS_ANGULAR_BLEND = float(options.brightness_angular_blend)
    if options.trail_base_resolution_factor is not None:
        config.set_trail_base_resolution_factor(float(options.trail_base_resolution_factor))
    if options.trail_step_scale is not None:
        config.set_trail_step_scale(float(options.trail_step_scale))
    if options.orbit_radius_mode is not None:
        config.ORBIT_RADIUS_MODE = str(options.orbit_radius_mode).strip().lower()
    if options.orbit_radius_power is not None:
        config.ORBIT_RADIUS_POWER = float(options.orbit_radius_power)
    if options.marker_size_mode is not None:
        config.BODY_MARKER_SIZE_MODE = str(options.marker_size_mode).strip().lower()
    if options.marker_gamma is not None:
        config.BODY_MARKER_RADIUS_POWER_FACTOR = max(0.5, float(options.marker_gamma))
    if options.selection_expression is not None:
        config.set_render_selection_expression(options.selection_expression)
    else:
        config.set_render_selection_expression(None)
    if options.center_body is not None:
        config.set_observer_center_body(options.center_body)

    if getattr(options, "bg_color", None) is not None:
        # runtime override of background color
        config.BACKGROUND_COLOR = tuple(int(c) for c in options.bg_color)

    center_key = str(config.OBSERVER_CENTER_BODY).strip().lower()
    if (
        options.selection_expression is not None
        and not config.selection_expression_includes_body(options.selection_expression, center_key)
    ):
        raise ValueError(
            f"Center body '{center_key}' is not included by selection expression '{options.selection_expression}'"
        )
    if center_key not in config.BODIES:
        raise ValueError(f"Center body '{center_key}' is not in current render set")


def _is_render_needed(now_utc: datetime) -> bool:
    if not os.path.exists(config.OUTPUT_PATH):
        return True
    if ephemeris.is_trail_update_due(now_utc):
        return True
    if render.is_overlay_update_due():
        return True
    return False


def run_render(options: RunOptions) -> None:
    _apply_runtime_config(options)

    now_utc = datetime.now(timezone.utc)
    if not _is_render_needed(now_utc):
        return

    states = ephemeris.get_body_states(now_utc)
    projected = projection.project_states(states)
    render.render_wallpaper(projected, now_utc)


def _options_from_args(args: argparse.Namespace) -> RunOptions:
    return RunOptions(
        show_labels=args.labels,
        glow_enabled=args.glow,
        image_width=args.width,
        image_height=args.height,
        yaw_deg=args.yaw,
        pitch_deg=args.pitch,
        roll_deg=args.roll,
        ssaa_scale=args.ssaa,
        celestial_scale_enabled=args.celestial_scale,
        dynamic_saturation=args.dynamic_saturation,
        saturation_angular_blend=args.saturation_angular_blend,
        brightness_angular_blend=args.brightness_angular_blend,
        trail_base_resolution_factor=args.trail_base_resolution_factor,
        trail_step_scale=args.trail_step_scale,
        orbit_radius_mode=args.orbit_radius_mode,
        orbit_radius_power=args.orbit_radius_power,
        marker_size_mode=args.marker_size_mode,
        marker_gamma=args.marker_gamma,
        center_body=args.center_body,
        selection_expression=args.selection,
        bg_color=args.bg_color,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate solar-system wallpaper")
    parser.add_argument("--labels", type=_parse_bool, default=True, help="Show body labels (True/False)")
    parser.add_argument("--glow", type=_parse_bool, default=True, help="Enable marker glow (True/False)")
    parser.add_argument("--width", type=int, default=2560, help="Output image width")
    parser.add_argument("--height", type=int, default=1440, help="Output image height")
    parser.add_argument("--yaw", type=float, default=0.0, help="View yaw in degrees")
    parser.add_argument("--pitch", type=float, default=0.0, help="View pitch in degrees")
    parser.add_argument("--roll", type=float, default=0.0, help="View roll in degrees")
    parser.add_argument("--ssaa", type=int, default=4, help="SSAA scale")
    parser.add_argument("--celestial-scale", type=_parse_bool, default=False, help="Enable or disable celestial guide circles (True/False)",)
    parser.add_argument("--dynamic-saturation", type=_parse_bool, default=True, help="Use acceleration-based trail saturation (True/False). False forces saturation to 1.0",)
    parser.add_argument("--saturation-angular-blend", type=float, default=0.0, help="Saturation blend: 0.0=linear speed, 1.0=angular speed",)
    parser.add_argument("--brightness-angular-blend", type=float, default=0.5, help="Brightness blend: 0.0=linear speed, 1.0=angular speed",)
    parser.add_argument("--trail-base-resolution-factor", type=float, default=10, help="Base trail resolution factor in hours. Lower value means higher trail sampling resolution",)
    parser.add_argument("--trail-step-scale", type=float, default=1.0, help="Trail scale factor: sets TRAIL_DAYS=365.25*BODY_SOLAR_YEAR_FACTOR[center]*scale and scales trail step minutes for all bodies",)
    parser.add_argument("--orbit-radius-mode", type=str, default='power', help="Orbit radius remap mode: linear, sqrt, log, power",)
    parser.add_argument("--orbit-radius-power", type=float, default=0.5, help="Exponent used when orbit radius mode is power",)
    parser.add_argument("--marker-size-mode", type=str, choices=("linear", "angular"), default=None, help="Marker size mode: linear (radius) or angular (apparent size from center body)",)
    parser.add_argument("--marker-gamma", type=float, default=None, help="Marker gamma factor. Applied as metric ** (1/gamma), clamped to gamma >= 0.5",)
    parser.add_argument("--center-body", type=str, default="venus", help="Observer center body key (e.g. earth, sun, moon, mars)",)
    parser.add_argument("--selection", type=str, default='innerplanets', help="Body selection expression. Examples: 'planets AND moon', 'dwarf planets AND outer planets'. Sun is always included.",)
    parser.add_argument("--bg-color", type=_parse_color, default=None, help="Background color name or hex code (e.g. 'black' or '#ff00ff')")
    return parser.parse_args()


def main() -> None:
    run_render(_options_from_args(_parse_args()))


if __name__ == "__main__":
    main()