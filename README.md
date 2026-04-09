# Optimized Rewrite

This folder contains a clean rewrite of the project-owned runtime code while keeping the original codebase untouched.

## Included rewritten files

- `config.py`
- `dwarf_planet_orbits.py`
- `ephemeris.py`
- `projection.py`
- `trail_kinematics.py`
- `render.py`
- `main.py`
- `run_wallpaper.ps1`
- `setup_wallpaper_scheduler.ps1`
- `set_geocentric_wallpaper.ps1`

## Key improvements

- Cleaner module-level structure and documentation.
- More robust path handling from nested folder layout.
- Cached rotation matrix in projection to reduce trigonometric recomputation overhead.
- Ephemeris current-position optimization by reusing center-body current vector.
- Cleaner scheduler argument normalization.
- Wallpaper setter avoids redundant `Add-Type` registration.
- Existing cycle cache + rotate behavior retained in `run_wallpaper.ps1`.

## Quick run

From project root:

```powershell
.\optimized_rewrite\run_wallpaper.ps1 -VerboseLog
```

Example with fixed selection:

```powershell
.\optimized_rewrite\run_wallpaper.ps1 -VerboseLog -MainArgs '--selection','earth'
```

Example with per-update rotation:

```powershell
.\optimized_rewrite\run_wallpaper.ps1 -VerboseLog -MainArgs '--selection','innerplanets','--RotateZ=2','--RotateX=1','--RotateY=-1'
```

## Scheduler setup (dry-run)

```powershell
.\optimized_rewrite\setup_wallpaper_scheduler.ps1 -TaskName 'SolarWallpaperAutoUpdate_Rewrite' -IntervalMinutes 30 -NoCycle -MainArgs '--selection','innerplanets','--RotateZ=2' -WhatIf
```

## Smoke test harness

Run:

```powershell
.\optimized_rewrite\smoke_test.ps1
```

This script performs a minimal end-to-end check for:

- cycle cache miss/miss/hit sequence
- rotation flag application
- scheduler setup dry-run parsing
