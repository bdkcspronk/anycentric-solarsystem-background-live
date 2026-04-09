[CmdletBinding()]
param(
    [ValidateRange(1, 100)]
    [int]$Iterations = 5,
    [ValidateRange(0, 10)]
    [int]$WarmupRuns = 1,
    [string[]]$MainArgs,
    [switch]$VerboseRunner,
    [switch]$ResetCycleState,
    [switch]$IgnoreSchedulerConfig
)

$ErrorActionPreference = 'Stop'

$rootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$originalRunner = Join-Path $rootDir 'run_wallpaper.ps1'
$rewriteRunner = Join-Path $rootDir 'optimized_rewrite\run_wallpaper.ps1'

if (-not (Test-Path $originalRunner)) {
    throw "Original runner not found: $originalRunner"
}
if (-not (Test-Path $rewriteRunner)) {
    throw "Rewrite runner not found: $rewriteRunner"
}

function Reset-RunnerState {
    param([string]$RunnerDir)

    $cycleState = Join-Path $RunnerDir 'wallpaper_cycle_state.json'
    $rotationState = Join-Path $RunnerDir 'wallpaper_rotation_state.json'
    $cycleCache = Join-Path $RunnerDir 'wallpaper_cycle_cache'

    Remove-Item -Force $cycleState -ErrorAction SilentlyContinue
    Remove-Item -Force $rotationState -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force $cycleCache -ErrorAction SilentlyContinue
}

function Invoke-TimedRunner {
    param(
        [string]$RunnerPath,
        [string]$Label,
        [int]$WarmupRuns,
        [int]$Iterations,
        [string[]]$MainArgs,
        [bool]$VerboseRunner
    )

    $runnerDir = Split-Path -Parent $RunnerPath
    if ($ResetCycleState) {
        Reset-RunnerState -RunnerDir $runnerDir
    }

    if ($WarmupRuns -gt 0) {
        for ($w = 1; $w -le $WarmupRuns; $w++) {
            $cfgArgs = @{}
            if ($IgnoreSchedulerConfig) {
                $cfgArgs.ConfigPath = (Join-Path $runnerDir '__benchmark_no_config__.json')
            }

            $hasMainArgs = ($null -ne $MainArgs -and $MainArgs.Count -gt 0)
            if ($VerboseRunner -and $hasMainArgs) {
                & $RunnerPath @cfgArgs -MainArgs $MainArgs -VerboseLog
            } elseif ($VerboseRunner) {
                & $RunnerPath @cfgArgs -VerboseLog
            } elseif ($hasMainArgs) {
                & $RunnerPath @cfgArgs -MainArgs $MainArgs
            } else {
                & $RunnerPath @cfgArgs
            }
            if ($LASTEXITCODE -ne 0) {
                throw "$Label warmup run $w failed with exit code $LASTEXITCODE"
            }
        }
    }

    $times = New-Object System.Collections.Generic.List[double]
    for ($i = 1; $i -le $Iterations; $i++) {
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        $cfgArgs = @{}
        if ($IgnoreSchedulerConfig) {
            $cfgArgs.ConfigPath = (Join-Path $runnerDir '__benchmark_no_config__.json')
        }

        $hasMainArgs = ($null -ne $MainArgs -and $MainArgs.Count -gt 0)
        if ($VerboseRunner -and $hasMainArgs) {
            & $RunnerPath @cfgArgs -MainArgs $MainArgs -VerboseLog
        } elseif ($VerboseRunner) {
            & $RunnerPath @cfgArgs -VerboseLog
        } elseif ($hasMainArgs) {
            & $RunnerPath @cfgArgs -MainArgs $MainArgs
        } else {
            & $RunnerPath @cfgArgs
        }
        $exit = $LASTEXITCODE
        $sw.Stop()

        if ($exit -ne 0) {
            throw "$Label measured run $i failed with exit code $exit"
        }

        $elapsedMs = [math]::Round($sw.Elapsed.TotalMilliseconds, 2)
        $times.Add($elapsedMs)
        Write-Host ("{0} run {1}/{2}: {3} ms" -f $Label, $i, $Iterations, $elapsedMs)
    }

    $arr = $times.ToArray()
    [array]::Sort($arr)
    $avg = [math]::Round(($times | Measure-Object -Average).Average, 2)
    $min = [math]::Round(($times | Measure-Object -Minimum).Minimum, 2)
    $max = [math]::Round(($times | Measure-Object -Maximum).Maximum, 2)
    $median = if ($arr.Length % 2 -eq 1) {
        [math]::Round($arr[[int][math]::Floor($arr.Length / 2)], 2)
    } else {
        $mid = $arr.Length / 2
        [math]::Round((($arr[$mid - 1] + $arr[$mid]) / 2.0), 2)
    }

    return [pscustomobject]@{
        Label = $Label
        Runs = $Iterations
        Warmups = $WarmupRuns
        AverageMs = $avg
        MedianMs = $median
        MinMs = $min
        MaxMs = $max
    }
}

if ($null -ne $MainArgs -and $MainArgs.Count -gt 0) {
    Write-Host "Benchmark args: $($MainArgs -join ' ')"
} else {
    Write-Host "Benchmark args: <runner defaults>"
}
Write-Host "Warmups per runner: $WarmupRuns"
Write-Host "Measured runs per runner: $Iterations"
Write-Host "Ignore scheduler config: $([bool]$IgnoreSchedulerConfig)"

$orig = Invoke-TimedRunner -RunnerPath $originalRunner -Label 'original' -WarmupRuns $WarmupRuns -Iterations $Iterations -MainArgs $MainArgs -VerboseRunner:$VerboseRunner
$rewr = Invoke-TimedRunner -RunnerPath $rewriteRunner -Label 'rewrite' -WarmupRuns $WarmupRuns -Iterations $Iterations -MainArgs $MainArgs -VerboseRunner:$VerboseRunner

$delta = [math]::Round(($orig.AverageMs - $rewr.AverageMs), 2)
$ratio = if ($orig.AverageMs -gt 0) { [math]::Round(($rewr.AverageMs / $orig.AverageMs), 4) } else { 0 }
$percent = if ($orig.AverageMs -gt 0) { [math]::Round((100.0 * ($orig.AverageMs - $rewr.AverageMs) / $orig.AverageMs), 2) } else { 0 }

Write-Host ""
Write-Host "Summary"
@($orig, $rewr) | Format-Table -AutoSize
Write-Host ("Average delta (original - rewrite): {0} ms" -f $delta)
Write-Host ("Rewrite/original ratio: {0}" -f $ratio)
Write-Host ("Rewrite improvement: {0}%" -f $percent)
