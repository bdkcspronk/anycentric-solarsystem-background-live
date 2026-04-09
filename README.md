# Solar Background Wallpaper Automation (Windows)

Generate a solar-system wallpaper and optionally install a Windows scheduled task to update it.

This repository has been refactored into compact, single-responsibility Python modules (ephemeris, trail kinematics, rendering helpers) with a thin orchestration layer in `main.py`. Operational entrypoints are the two PowerShell scripts: `run_wallpaper.ps1` and `setup_wallpaper_scheduler.ps1`.

## Quick start

1. Create and activate a Python virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Run a single update (writes `wallpaper.png` in the project folder):

```powershell
.\run_wallpaper.ps1 -MainArgs "-Rotate"
```

Optional: run `main.py` directly while the venv is active for faster iteration:

```powershell
.venv\Scripts\python.exe main.py --glow True --labels True --width 2560 --height 1440
```

## Install or update the scheduler (dry-run)

```powershell
.\setup_wallpaper_scheduler.ps1 -TaskName "SolarWallpaperAutoUpdate" -IntervalMinutes 60 -MainArgs "--selection", "innerplanets AND ceres", "-Rotate" -WhatIf
```

Remove `-WhatIf` to perform the actual install/update.

## What the scripts do

- `run_wallpaper.ps1`: prepares args, activates the venv, calls `main.py`, and applies the wallpaper.
- `setup_wallpaper_scheduler.ps1`: creates or updates a Windows scheduled task that runs `run_wallpaper.ps1` on the given interval.

## High-level module map

- `main.py` — CLI parsing and render orchestration (applies runtime options into `config` then runs the pipeline).
- `config.py` — runtime configuration façade; selection and body-building logic delegated to `config_selection.py` and `config_body_factory.py`.
- Ephemeris group:
  - `ephemeris.py` — public orchestration: `is_trail_update_due()` and `get_body_states()`.
  - `ephemeris_types.py` — `BodyState` dataclass.
  - `ephemeris_kernel.py` — Skyfield loader and timescale helpers.
  - `ephemeris_cache.py` — trail cache read/write helpers.
  - `ephemeris_trails.py` — heliocentric/relative trail computation and incremental updates.
- Trail kinematics group:
  - `trail_kinematics.py` — orchestration and `compute_or_load_kinematics()`.
  - `trail_kinematics_types.py` — raw/derived kinematics dataclasses.
  - `trail_kinematics_cache.py` — cached raw kinematics I/O and signatures.
  - `trail_kinematics_math.py` — numeric computations and color policy.
- Render group:
  - `render.py` — top-level wallpaper composition and save.
  - `render_trail_layer.py` — trail image drawing and caching.
  - `render_markers.py` — marker shapes, glow, and labels.
  - `render_celestial.py` — celestial scale overlay drawing.
  - `render_overlay_state.py` — overlay signature persistence.
  - `render_utils.py` — small helpers (color revalue, fonts, clamp).

Other helpers: `projection.py`, `dwarf_planet_orbits.py`, and various JSON state/cache files under the project root.

## Configuration notes

- Default output: `wallpaper.png` at `2560x1440`.
- Many runtime options are available via `main.py` CLI or forwarded via `-MainArgs` from the scheduler; CLI args override values in `config.py` for that run only.
- Common tuning points in `config.py`: `IMAGE_WIDTH`, `IMAGE_HEIGHT`, `SHOW_BODY_LABELS`, `SSAA_SCALE`, `ORBIT_RADIUS_MODE`, `ORBIT_RADIUS_POWER`, `TRAIL_DAYS`, `TRAIL_STEP_MINUTES`.

## Development & validation

1. Activate the venv and install requirements (see above).
2. Run a single update to validate the end-to-end pipeline:

```powershell
.\run_wallpaper.ps1 -MainArgs "-Rotate"
```

3. If you refactor modules, update `FUNCTIONAL_SUMMARY.md` and `README.md`, then run the smoke test above.

## Troubleshooting

- If editor diagnostics show unresolved imports (e.g., `numpy`, `skyfield`, `PIL`), point your editor at the project's `.venv` interpreter and reinstall `requirements.txt` there.
- If the scheduled task fails, run `.
un_wallpaper.ps1 -VerboseLog` to inspect runtime errors.

## Files mentioned in this README

[main.py](main.py) • [config.py](config.py) • [ephemeris.py](ephemeris.py) • [projection.py](projection.py) • [trail_kinematics.py](trail_kinematics.py) • [render.py](render.py) • [run_wallpaper.ps1](run_wallpaper.ps1) • [setup_wallpaper_scheduler.ps1](setup_wallpaper_scheduler.ps1) • [FUNCTIONAL_SUMMARY.md](FUNCTIONAL_SUMMARY.md)

---

If you'd like, I can also update `FUNCTIONAL_SUMMARY.md` to include the new module map and a brief responsibilities table.
