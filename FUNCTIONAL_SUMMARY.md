# Functional Summary of Existing Programs

This document summarizes the top-layer behavior and responsibilities of all project-owned `.py` and `.ps1` files in the original implementation.

## System-level flow

1. `run_wallpaper.ps1` is the operational entrypoint for manual runs and scheduled runs.
2. It assembles effective args (from config + CLI), optionally performs center-body cycling and/or rotation transforms, then invokes `main.py`.
3. `main.py` mutates runtime config, decides whether rendering is needed, computes ephemeris and projection, then renders `geocentric.png`.
4. `set_geocentric_wallpaper.ps1` applies the generated image as Windows wallpaper.
5. `setup_wallpaper_scheduler.ps1` installs and maintains a scheduled task that runs `run_wallpaper.ps1` hidden via VBScript.

---

## Python files

## `config.py`

Top-layer purpose:
- Central runtime configuration and mutable state registry.

Main functionality:
- Defines visual/render settings (image size, scale, labels, anti-aliasing, view angles).
- Defines body metadata (targets, marker radii/brightness, trail step multipliers).
- Defines orbital display remapping settings (`ORBIT_RADIUS_MODE`, `ORBIT_RADIUS_POWER`, body multipliers).
- Defines selection groups and parser (`planets`, `innerplanets`, `dwarfplanets`, explicit body names).
- Maintains selected body set (`BODIES`) based on expression / mode flags.
- Recomputes dependent trail timing when center body or trail sampling changes.

Key side effects:
- Several setters (`set_render_selection_expression`, `set_observer_center_body`, trail setters) mutate module globals and rebuild active body dictionaries.

## `dwarf_planet_orbits.py`

Top-layer purpose:
- Provides analytic Keplerian fallback ephemeris for dwarf planets not pulled from DE440s by the main kernel path.

Main functionality:
- Defines orbital elements for Ceres, Pluto, Eris, Haumea, Makemake, Gonggong, Quaoar.
- Solves Kepler equation and computes heliocentric position at a datetime.
- Produces geocentric vectors by subtracting Earth heliocentric vector.
- Supports both single-sample and trail vector generation.

Key side effects:
- None (pure computation module).

## `ephemeris.py`

Top-layer purpose:
- Computes body positions and trails in observer-centered coordinates.

Main functionality:
- Loads Skyfield kernel/timescale lazily and caches in-process.
- Computes effective trail horizon constrained by kernel date range.
- Manages persistent trail cache (`trail_cache.json`) with per-body incremental updates.
- For each body:
  - If center body: returns zero vector trail.
  - Else: updates/recomputes cached relative trail vectors to center target.
  - Computes current exact-time relative position for marker placement.
- Exposes update decision function (`is_trail_update_due`) and state generation (`get_body_states`).

Key side effects:
- Reads/writes trail cache file on disk.

## `projection.py`

Top-layer purpose:
- Converts observer-centered AU coordinates into screen coordinates.

Main functionality:
- Applies yaw/pitch/roll rotation.
- Applies radial remap (`linear`, `power`, `sqrt`, `log`) and per-body distance multiplier.
- Computes dynamic projection scale from full trail extents to keep content in frame.
- Projects current position and each trail sample to pixel coordinates.

Key side effects:
- None (pure transform module).

## `trail_kinematics.py`

Top-layer purpose:
- Computes per-segment trail color kinematics with persistent per-body cache.

Main functionality:
- Derives segment metrics from trail samples:
  - Linear speed, apparent angular speed, acceleration, directional hue.
- Caches raw kinematics per body and step size in `trail_kinematics_cache/` keyed by trail signature.
- Computes global maxima across bodies for normalized brightness/saturation scaling.
- Produces final per-segment RGB colors used by renderer.

Key side effects:
- Reads/writes per-body JSON cache files under `trail_kinematics_cache/`.

## `render.py`

Top-layer purpose:
- Produces final wallpaper image from projected states.

Main functionality:
- Computes overlay signature to decide if overlay update is required.
- Builds/loads trail layer cache (`trail_layer_cache.png` + metadata signature).
- Draws additive trail layers body-by-body using per-segment colors.
- Draws optional celestial reference circles (XY/XZ/YZ planes).
- Draws body markers and labels with body-specific styles.
- Performs SSAA downsampling and writes final output PNG.

Key side effects:
- Writes `geocentric.png`.
- Reads/writes trail layer cache files.
- Reads/writes overlay signature state file.

## `main.py`

Top-layer purpose:
- Python CLI entrypoint that wires configuration, ephemeris, projection, and rendering.

Main functionality:
- Parses CLI args for rendering options, center body, selection, and scaling behavior.
- Applies runtime overrides to mutable config globals.
- Validates center-body compatibility with selection expression.
- Short-circuits when both trail cache and overlay are up to date.
- Otherwise computes states -> projection -> render.

Key side effects:
- Triggers cache writes and final image write indirectly via dependent modules.

---

## PowerShell files

## `run_wallpaper.ps1`

Top-layer purpose:
- Operational orchestrator for each wallpaper update run.

Main functionality:
- Loads runtime config JSON (`wallpaper_scheduler_config.json`) and optional direct `-MainArgs` override.
- Optional center-body cycle mode:
  - Derives selected body set via inline Python call.
  - Advances round-robin cycle state (`wallpaper_cycle_state.json`).
  - Injects `--center-body=...` and adjusts `--selection` when needed (sun inclusion case).
- Optional rotation wrapper flags:
  - `--RotateZ`, `--RotateX`, `--RotateY` (incremental per run).
  - `--Rotate` / `-Rotate` random mode.
  - Persists rotation state (`wallpaper_rotation_state.json`).
- Optional cycle image cache (when cycle enabled and rotation disabled):
  - Reuses cached per-body image when args signature matches.
  - Stores per-body image+metadata in `wallpaper_cycle_cache/`.
- Calls Python `main.py`, then applies wallpaper through setter script.

Key side effects:
- Reads/writes cycle state, rotation state, and cycle cache files.
- Launches Python rendering.
- Calls wallpaper setter.

## `setup_wallpaper_scheduler.ps1`

Top-layer purpose:
- Installs/updates/removes Windows Task Scheduler automation.

Main functionality:
- Builds scheduler config JSON with interval, main args, and cycle mode.
- Supports interval by hours or minutes.
- Registers two triggers for one task:
  - At logon.
  - Repeating interval trigger.
- Uses hidden launcher (`wscript.exe` + `run_wallpaper_hidden.vbs`) to avoid visible PowerShell window.
- Supports uninstall and run-now paths.

Key side effects:
- Writes scheduler config JSON.
- Registers/unregisters scheduled task.

## `set_geocentric_wallpaper.ps1`

Top-layer purpose:
- Applies a PNG/JPG file as desktop wallpaper in Windows.

Main functionality:
- Resolves relative image path.
- Sets registry style values (fill mode).
- Calls `SystemParametersInfo` (`user32.dll`) to apply wallpaper and notify system.

Key side effects:
- Modifies HKCU desktop style keys.
- Updates active desktop wallpaper.

---

## Performance-sensitive layers in current implementation

1. Ephemeris updates and trail recomputation/cache correctness.
2. Trail kinematics cache hit rate and signature granularity.
3. Trail rendering (many line draws at SSAA resolution).
4. PowerShell argument orchestration overhead and correctness.

These areas are the primary focus for the rewrite under `optimized_rewrite/` while preserving behavior.