"""Post-process brightness_values.json to produce normalized 0..1 and gamma-scaled values.

This reads `brightness_values.json`, uses `brightness_linear_ratio_to_sun` and applies
norm = ratio / (ratio + earth_ratio) and final = norm ** gamma. Writes back the file
with `brightness_normalized` and `brightness_final` fields and prints a sample.
"""
from __future__ import annotations

import json
from pathlib import Path

BP = Path(__file__).resolve().parent / "brightness_values.json"
data = json.loads(BP.read_text(encoding="utf-8"))

gamma = 0.5
earth = data.get("earth", {})
earth_ratio = earth.get("brightness_linear_ratio_to_sun")
if earth_ratio is None or earth_ratio <= 0:
    raise SystemExit("Invalid Earth ratio in brightness_values.json")

for k, v in data.items():
    if k.startswith("__"):
        continue
    ratio = v.get("brightness_linear_ratio_to_sun")
    if ratio is None or not isinstance(ratio, (int, float)) or ratio <= 0:
        v["brightness_normalized"] = None
        v["brightness_final"] = None
    else:
        norm = float(ratio) / (float(ratio) + float(earth_ratio))
        final = norm ** gamma
        v["brightness_normalized"] = norm
        v["brightness_final"] = final

data["__meta__"] = {"gamma": gamma, "method": "ratio/(ratio+earth_ratio)"}
BP.write_text(json.dumps(data, indent=2), encoding="utf-8")

print("Wrote normalized brightness values to:", BP)
print("Sample (name: final):")
for name in ("sun", "mercury", "venus", "earth", "mars", "jupiter", "pluto"):
    item = data.get(name, {})
    print(f"{name}: {item.get('brightness_final')}")
