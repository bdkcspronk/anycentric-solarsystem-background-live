"""Compute per-body brightness using simple heliocentric flux and disk area.

Outputs a JSON file `brightness_values.json` with raw, log, and normalized values.
Normalization uses direct Sun ratio (brightness_linear_ratio_to_sun), plus gamma shaping.

Formula used (per user request):
    flux = I0 / (4 * pi * r_au ** 2)
    disk_area = pi * R_meters ** 2
    brightness = flux * disk_area

Then compute natural log: ln(brightness), and normalized_log = ln(brightness) / ln(brightness_earth).
Also emit linear ratio = brightness / brightness_earth for reference.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

# Solar constant at 1 AU (W/m^2)
I0 = 1361.0

# Per-body physical data: semi-major axis (AU) and mean radius (km).
# Values are approximate and intended for relative brightness calculations.
DATA = {
    "sun": {"a_au": 0.0, "radius_km": 695700.0},
    "mercury": {"a_au": 0.387098, "radius_km": 2439.7},
    "venus": {"a_au": 0.723332, "radius_km": 6051.8},
    "earth": {"a_au": 1.0, "radius_km": 6371.0},
    "moon": {"a_au": 1.0, "radius_km": 1737.1},
    "mars": {"a_au": 1.523679, "radius_km": 3389.5},
    "jupiter": {"a_au": 5.2044, "radius_km": 69911.0},
    "saturn": {"a_au": 9.5826, "radius_km": 58232.0},
    "uranus": {"a_au": 19.2184, "radius_km": 25362.0},
    "neptune": {"a_au": 30.110387, "radius_km": 24622.0},
    "ceres": {"a_au": 2.7675, "radius_km": 473.0},
    "pluto": {"a_au": 39.482, "radius_km": 1188.3},
    "eris": {"a_au": 67.69, "radius_km": 1163.0},
    "haumea": {"a_au": 43.116, "radius_km": 816.0},
    "makemake": {"a_au": 45.499, "radius_km": 715.0},
    "gonggong": {"a_au": 66.895, "radius_km": 600.0},
    "quaoar": {"a_au": 43.694, "radius_km": 555.0},
}


def compute_brightness(a_au: float, radius_km: float) -> float:
    """Compute brightness per user formula: (I0 / r^2) * (pi * R^2).

    a_au == 0 (sun) is treated specially: we use the solar constant `I0` as the
    flux at 1 AU and multiply by the solar disk area to get an apparent disk
    brightness for the Sun (so other bodies are normalized to the Sun).
    """
    if a_au <= 0:
        # caller should handle the Sun specially; return inf as placeholder
        return float("inf")
    # flux scales as 1/r^2 (constants like 4*pi cancel for relative comparisons)
    flux = I0 / (a_au * a_au)
    r_m = radius_km * 1000.0
    disk_area = math.pi * (r_m ** 2)
    return flux * disk_area


def main() -> None:
    out: dict[str, dict] = {}

    # compute raw brightness for each body
    for name, v in DATA.items():
        raw = compute_brightness(v["a_au"], v["radius_km"])
        out[name] = {"semi_major_au": v["a_au"], "radius_km": v["radius_km"], "brightness_raw": raw}
    # Sun reference: compute a representative raw brightness for the Sun's disk
    sun_entry = out.get("sun")
    if sun_entry is None:
        raise RuntimeError("Sun entry missing from DATA")
    sun_r_m = sun_entry["radius_km"] * 1000.0
    sun_disk = math.pi * (sun_r_m ** 2)
    sun_raw = I0 * sun_disk

    if not math.isfinite(sun_raw):
        raise RuntimeError("Invalid Sun brightness computed")

    # compute linear ratios to Sun
    for name, obj in out.items():
        raw = obj["brightness_raw"]
        if name == "sun":
            obj["brightness_log"] = math.log(sun_raw)
            obj["brightness_linear_ratio_to_sun"] = 1.0
        elif raw <= 0 or not math.isfinite(raw):
            obj["brightness_log"] = None
            obj["brightness_linear_ratio_to_sun"] = None
        else:
            obj["brightness_log"] = math.log(raw)
            obj["brightness_linear_ratio_to_sun"] = raw / sun_raw

    # Normalization step (no logs): use direct ratio to Sun, then apply gamma
    # to keep dim bodies visible.
    gamma = 0.02
    for name, obj in out.items():
        ratio = obj.get("brightness_linear_ratio_to_sun")
        if ratio is None or not math.isfinite(ratio) or ratio <= 0:
            obj["brightness_normalized"] = None
            obj["brightness_final"] = None
        else:
            norm = float(ratio)
            final = float(norm) ** float(gamma)
            obj["brightness_normalized"] = norm
            obj["brightness_final"] = final

    # also include metadata
    metadata = {"gamma": gamma, "normalization": "ratio_to_sun", "sun_raw": sun_raw}
    out["__meta__"] = metadata

    out_path = Path(__file__).resolve().parent / "brightness_values.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    print(f"Wrote brightness values to: {out_path}")


if __name__ == "__main__":
    main()
