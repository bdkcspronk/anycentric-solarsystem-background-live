$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $scriptDir
Set-Location $root

Write-Host "[1/5] Reset rewritten cycle/cache state"
Remove-Item -Recurse -Force "$scriptDir\wallpaper_cycle_cache" -ErrorAction SilentlyContinue
Remove-Item -Force "$scriptDir\wallpaper_cycle_state.json" -ErrorAction SilentlyContinue

Write-Host "[2/5] Run 1 (expect cycle cache miss: earth)"
& "$scriptDir\run_wallpaper.ps1" -VerboseLog -MainArgs '--selection','earth'
if ($LASTEXITCODE -ne 0) { throw "Run 1 failed" }

Write-Host "[3/5] Run 2 (expect cycle cache miss: sun)"
& "$scriptDir\run_wallpaper.ps1" -VerboseLog -MainArgs '--selection','earth'
if ($LASTEXITCODE -ne 0) { throw "Run 2 failed" }

Write-Host "[4/5] Run 3 (expect cycle cache hit: earth)"
& "$scriptDir\run_wallpaper.ps1" -VerboseLog -MainArgs '--selection','earth'
if ($LASTEXITCODE -ne 0) { throw "Run 3 failed" }

Write-Host "[5/5] Rotation check + scheduler dry-run"
& "$scriptDir\run_wallpaper.ps1" -VerboseLog -MainArgs '--selection','innerplanets','--RotateZ=2','--RotateX=1','--RotateY=-1'
if ($LASTEXITCODE -ne 0) { throw "Rotation check failed" }

& "$scriptDir\setup_wallpaper_scheduler.ps1" -TaskName 'SolarWallpaperAutoUpdate_Rewrite' -IntervalMinutes 30 -NoCycle -MainArgs '--selection','innerplanets','--RotateZ=2' -WhatIf
if ($LASTEXITCODE -ne 0) { throw "Scheduler dry-run failed" }

Write-Host "Smoke tests completed successfully."
