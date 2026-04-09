"""Shared rendering utility helpers."""

from __future__ import annotations

import colorsys
from functools import lru_cache

from PIL import ImageFont


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def revalue_rgb(color: tuple[int, int, int], target_value: float | int | None) -> tuple[int, int, int]:
    """Revalue an RGB color to a target V (0..1 float or 0..255 int)."""
    r, g, b = color
    h, s, _ = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    if target_value is None:
        target_v = 1.0
    elif isinstance(target_value, int):
        target_v = clamp01(float(target_value) / 255.0)
    else:
        target_v = clamp01(float(target_value))
    rr, gg, bb = colorsys.hsv_to_rgb(h, s, target_v)
    return (int(round(rr * 255.0)), int(round(gg * 255.0)), int(round(bb * 255.0)))


@lru_cache(maxsize=32)
def get_label_font(size_px: int) -> ImageFont.ImageFont:
    size = max(8, int(size_px))
    for font_name in ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(font_name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()
