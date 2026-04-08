[CmdletBinding(SupportsShouldProcess=$true, PositionalBinding=$false)]
param(
    [string]$TaskName = "SolarWallpaperAutoUpdate",
    [ValidateRange(1, 168)]
    [int]$IntervalHours = 1,
    [string[]]$MainArgs = @(),
    [string[]]$SelectionCycle = @(),
    [switch]$Uninstall,
    [switch]$RunNow
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$runnerPath = Join-Path $scriptDir "run_wallpaper.ps1"
$hiddenRunnerPath = Join-Path $scriptDir "run_wallpaper_hidden.vbs"
$configPath = Join-Path $scriptDir "wallpaper_scheduler_config.json"

# Normalize cases where MainArgs is passed as one combined token like
# "'--pitch','70'" (can happen depending on caller shell quoting).
if ($MainArgs.Count -eq 1 -and $MainArgs[0] -like "*,*") {
    $raw = $MainArgs[0]
    $parts = $raw -split ","
    $normalized = @()
    foreach ($p in $parts) {
        $v = $p.Trim()
        $v = $v.Trim("'", '"')
        if (-not [string]::IsNullOrWhiteSpace($v)) {
            $normalized += $v
        }
    }
    if ($normalized.Count -gt 0) {
        $MainArgs = $normalized
    }
}

if (-not (Test-Path $runnerPath)) {
    throw "Runner script not found: $runnerPath"
}
if (-not (Test-Path $hiddenRunnerPath)) {
    throw "Hidden runner script not found: $hiddenRunnerPath"
}

if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        if ($PSCmdlet.ShouldProcess($TaskName, "Unregister scheduled task")) {
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
            Write-Host "Removed scheduled task '$TaskName'."
        }
    } else {
        Write-Host "Task '$TaskName' was not found."
    }
    return
}

$config = [ordered]@{
    interval_hours = $IntervalHours
    main_args = $MainArgs
}

if ($SelectionCycle.Count -gt 0) {
    $config.selection_cycle = $SelectionCycle
}

if ($PSCmdlet.ShouldProcess($configPath, "Write scheduler config")) {
    $config | ConvertTo-Json -Depth 5 | Set-Content -Path $configPath -Encoding UTF8
}

$interval = New-TimeSpan -Hours $IntervalHours
$duration = New-TimeSpan -Days 3650
$triggerLogon = New-ScheduledTaskTrigger -AtLogOn
$triggerRepeat = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) -RepetitionInterval $interval -RepetitionDuration $duration

$wscript = Join-Path $env:WINDIR "System32\wscript.exe"
$argStr = "//B //nologo `"$hiddenRunnerPath`""
$action = New-ScheduledTaskAction -Execute $wscript -Argument $argStr -WorkingDirectory $scriptDir

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

if ($PSCmdlet.ShouldProcess($TaskName, "Register/Update scheduled task")) {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger @($triggerLogon, $triggerRepeat) `
        -Principal $principal `
        -Settings $settings `
        -Force `
        -ErrorAction Stop | Out-Null

    Write-Host "Scheduled task '$TaskName' is active."
    Write-Host "Interval: every $IntervalHours hour(s)."
    if ($MainArgs.Count -gt 0) {
        Write-Host "main.py args: $($MainArgs -join ' ')"
    }
    if ($SelectionCycle.Count -gt 0) {
        Write-Host "selection cycle: $($SelectionCycle -join ' | ')"
    }
}

if ($RunNow) {
    if ($PSCmdlet.ShouldProcess($TaskName, "Start task now")) {
        Start-ScheduledTask -TaskName $TaskName
        Write-Host "Started '$TaskName'."
    }
}
