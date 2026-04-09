"""Top-level wallpaper render orchestration."""

from __future__ import annotations

from datetime import datetime
import os
import time

from PIL import Image, ImageChops

import config
from projection import ProjectedBody
from render_celestial import draw_celestial_scale_overlay
from render_markers import draw_markers
from render_overlay_state import is_overlay_update_due, mark_overlay_rendered
from render_trail_layer import get_trail_layer_image
from trail_kinematics import compute_or_load_kinematics


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


def render_wallpaper(projected: dict[str, ProjectedBody], at_time: datetime) -> Image.Image:
    del at_time

    ssaa_scale = max(1, int(config.SSAA_SCALE))
    render_width = config.IMAGE_WIDTH * ssaa_scale
    render_height = config.IMAGE_HEIGHT * ssaa_scale

    image = Image.new("RGB", (render_width, render_height), config.BACKGROUND_COLOR)
    kin_bundle = compute_or_load_kinematics(projected)
    trail_image = get_trail_layer_image(projected, kin_bundle, render_width, render_height, ssaa_scale)
    image = ImageChops.add(image, trail_image)

    draw_celestial_scale_overlay(image, projected, ssaa_scale)
    draw_markers(image, projected, kin_bundle, ssaa_scale)

    if ssaa_scale > 1:
        image = image.resize((config.IMAGE_WIDTH, config.IMAGE_HEIGHT), resample=Image.Resampling.LANCZOS)

    _save_output_image(image, config.OUTPUT_PATH)
    mark_overlay_rendered()
    return image
