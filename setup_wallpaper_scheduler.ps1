[CmdletBinding(SupportsShouldProcess=$true, PositionalBinding=$false)]
param(
    [string]$TaskName = "SolarWallpaperAutoUpdate",
    [ValidateRange(1, 168)]
    [int]$IntervalHours = 1,
    [ValidateRange(0, 10080)]
    [int]$IntervalMinutes = 0,
    [string[]]$MainArgs = @(),
    [string[]]$SelectionCycle = @(),
    [switch]$NoCycle,
    [switch]$Uninstall,
    [switch]$RunNow
)

$ErrorActionPreference = "Stop"

function Normalize-ArgumentArray {
    param([string[]]$InputArgs)

    if ($null -eq $InputArgs) {
        return ,@()
    }

    # Normalize cases where MainArgs is passed as one combined token like
    # "'--pitch','70'" (can happen depending on caller shell quoting).
    if ($InputArgs.Count -eq 1 -and $InputArgs[0] -like "*,*") {
        $raw = $InputArgs[0]
        $parts = $raw -split ","
        $normalized = @()
        foreach ($p in $parts) {
            $v = $p.Trim().Trim("'", '"')
            if (-not [string]::IsNullOrWhiteSpace($v)) {
                $normalized += $v
            }
        }
        if ($normalized.Count -gt 0) {
            return ,$normalized
        }
    }

    return ,$InputArgs
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$runnerPath = Join-Path $scriptDir "run_wallpaper.ps1"
$hiddenRunnerPath = Join-Path $scriptDir "run_wallpaper_hidden.vbs"
$configPath = Join-Path $scriptDir "wallpaper_scheduler_config.json"

$MainArgs = Normalize-ArgumentArray -InputArgs $MainArgs

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
    main_args = $MainArgs
}

# Prefer explicit minutes when provided, otherwise fall back to hours.
if ($IntervalMinutes -gt 0) {
    $config.interval_minutes = $IntervalMinutes
} else {
    $config.interval_hours = $IntervalHours
}

if ($SelectionCycle.Count -gt 0) {
    $config.selection_cycle = $SelectionCycle
}

# Cycle enabled unless user passed -NoCycle
$cycleEnabled = -not [bool]$NoCycle
$config.cycle_enabled = $cycleEnabled

if ($PSCmdlet.ShouldProcess($configPath, "Write scheduler config")) {
    $config | ConvertTo-Json -Depth 5 | Set-Content -Path $configPath -Encoding UTF8
}

$interval = if ($IntervalMinutes -gt 0) { New-TimeSpan -Minutes $IntervalMinutes } else { New-TimeSpan -Hours $IntervalHours }
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
    if ($IntervalMinutes -gt 0) {
        Write-Host "Interval: every $IntervalMinutes minute(s)."
    } else {
        Write-Host "Interval: every $IntervalHours hour(s)."
    }
    if ($MainArgs.Count -gt 0) {
        Write-Host "main.py args: $($MainArgs -join ' ')"
    }
    if ($SelectionCycle.Count -gt 0) {
        Write-Host "selection cycle: $($SelectionCycle -join ' | ')"
    }
    Write-Host "cycle enabled: $cycleEnabled"
}

if ($RunNow) {
    if ($PSCmdlet.ShouldProcess($TaskName, "Start task now")) {
        Start-ScheduledTask -TaskName $TaskName
        Write-Host "Started '$TaskName'."
    }
}
