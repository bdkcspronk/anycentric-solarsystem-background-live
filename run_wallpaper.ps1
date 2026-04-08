param(
    [string]$ConfigPath = "",
    [string[]]$MainArgs,
    [switch]$VerboseLog
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Join-Path $scriptDir "wallpaper_scheduler_config.json"
}
$cycleStatePath = Join-Path $scriptDir "wallpaper_cycle_state.json"

$pythonExe = Join-Path $scriptDir ".venv\Scripts\python.exe"
$mainPy = Join-Path $scriptDir "main.py"

if (-not (Test-Path $pythonExe)) {
    throw "Python executable not found: $pythonExe"
}
if (-not (Test-Path $mainPy)) {
    throw "main.py not found: $mainPy"
}

$forwardArgs = @()
if (Test-Path $ConfigPath) {
    $cfg = Get-Content -Raw -Path $ConfigPath | ConvertFrom-Json
    if ($null -ne $cfg.main_args) {
        $forwardArgs = @($cfg.main_args)
    }
}

if ($null -ne $MainArgs -and $MainArgs.Count -gt 0) {
    $forwardArgs = @($MainArgs)
}

function Test-HasArg {
    param(
        [string[]]$ArgList,
        [string]$Name
    )
    $pattern = "^(?i)--$([Regex]::Escape($Name))(=|$)"
    for ($i = 0; $i -lt $ArgList.Count; $i++) {
        $a = [string]$ArgList[$i]
        if ($a -match $pattern) {
            return $true
        }
    }
    return $false
}

function Get-ArgValue {
    param(
        [string[]]$ArgList,
        [string]$Name
    )
    $prefix = "--$Name="
    for ($i = 0; $i -lt $ArgList.Count; $i++) {
        $a = [string]$ArgList[$i]
        if ($a.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $a.Substring($prefix.Length)
        }
        if ($a.Equals("--$Name", [System.StringComparison]::OrdinalIgnoreCase)) {
            if (($i + 1) -lt $ArgList.Count) {
                return [string]$ArgList[$i + 1]
            }
            return ""
        }
    }
    return $null
}

function Set-ArgValue {
    param(
        [string[]]$ArgList,
        [string]$Name,
        [string]$Value
    )

    $result = @()
    $i = 0
    $found = $false
    while ($i -lt $ArgList.Count) {
        $a = [string]$ArgList[$i]
        if ($a.StartsWith("--$Name=", [System.StringComparison]::OrdinalIgnoreCase)) {
            if (-not $found) {
                $result += "--$Name=$Value"
                $found = $true
            }
            $i += 1
            continue
        }
        if ($a.Equals("--$Name", [System.StringComparison]::OrdinalIgnoreCase)) {
            if (-not $found) {
                $result += "--$Name"
                $result += "$Value"
                $found = $true
            }
            $i += 2
            continue
        }
        $result += $a
        $i += 1
    }

    if (-not $found) {
        $result += "--$Name=$Value"
    }
    return @($result)
}

function Remove-Arg {
    param(
        [string[]]$ArgList,
        [string]$Name
    )

    $result = @()
    $i = 0
    while ($i -lt $ArgList.Count) {
        $a = [string]$ArgList[$i]
        if ($a.StartsWith("--$Name=", [System.StringComparison]::OrdinalIgnoreCase)) {
            $i += 1
            continue
        }
        if ($a.Equals("--$Name", [System.StringComparison]::OrdinalIgnoreCase)) {
            $i += 2
            continue
        }
        $result += $a
        $i += 1
    }
    return @($result)
}

function Get-SelectedBodiesForExpression {
    param([string]$SelectionExpr)

    $exprForPy = if ($null -eq $SelectionExpr) { "" } else { $SelectionExpr }
    $code = @"
import json
import config

expr = '''$exprForPy'''.strip()
if expr:
    selected = set(config._evaluate_selection_expression(expr))
else:
    # Mirror main.py default when no explicit selection is passed.
    selected = set(config._evaluate_selection_expression('inner planets'))

ordered = [name for name in config.ALL_BODIES.keys() if name in selected]
print(json.dumps(ordered))
"@

    $raw = & $pythonExe -c $code
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($raw)) {
        return @()
    }
    try {
        return @($raw | ConvertFrom-Json)
    } catch {
        return @()
    }
}

function Get-NextCycledBody {
    param(
        [string[]]$Bodies,
        [string]$SelectionKey,
        [string]$StatePath
    )
    if ($Bodies.Count -eq 0) {
        return $null
    }

    $idx = 0
    $savedKey = ""
    if (Test-Path $StatePath) {
        try {
            $state = Get-Content -Raw -Path $StatePath | ConvertFrom-Json
            if ($null -ne $state.index) {
                $idx = [int]$state.index
            }
            if ($null -ne $state.selection_key) {
                $savedKey = [string]$state.selection_key
            }
        } catch {
            $idx = 0
            $savedKey = ""
        }
    }

    if (-not $savedKey.Equals($SelectionKey, [System.StringComparison]::Ordinal)) {
        $idx = 0
    }

    $idx = (($idx % $Bodies.Count) + $Bodies.Count) % $Bodies.Count
    $body = $Bodies[$idx]
    $nextIdx = ($idx + 1) % $Bodies.Count

    @{
        selection_key = $SelectionKey
        index = $nextIdx
    } | ConvertTo-Json | Set-Content -Path $StatePath -Encoding UTF8

    return $body
}

# Cycle center body inside the effective selection unless center body is explicitly provided.
if (-not (Test-HasArg -ArgList $forwardArgs -Name "center-body")) {
    $selectionExpr = Get-ArgValue -ArgList $forwardArgs -Name "selection"
    if ([string]::IsNullOrWhiteSpace($selectionExpr)) {
        $selectionExpr = "inner planets"
    }

    $cycleBodies = Get-SelectedBodiesForExpression -SelectionExpr $selectionExpr
    if (-not ($cycleBodies -contains "sun")) {
        $cycleBodies += "sun"
    }
    $selectionKey = "$selectionExpr|$($cycleBodies -join ',')"
    $nextBody = Get-NextCycledBody -Bodies $cycleBodies -SelectionKey $selectionKey -StatePath $cycleStatePath
    if (-not [string]::IsNullOrWhiteSpace($nextBody)) {
        if ($nextBody.Equals("sun", [System.StringComparison]::OrdinalIgnoreCase)) {
            # main.py requires center body to be explicitly included by selection expression.
            $selectionWithSun = "($selectionExpr) OR sun"
            $forwardArgs = Remove-Arg -ArgList $forwardArgs -Name "selection"
            $forwardArgs = @($forwardArgs + @("--selection", $selectionWithSun))
        }
        $forwardArgs = @($forwardArgs + @("--center-body=$nextBody"))
    }
}

if ($VerboseLog) {
    Write-Host "Running wallpaper generation..."
    Write-Host "Python: $pythonExe"
    Write-Host "Script: $mainPy"
    if ($forwardArgs.Count -gt 0) {
        Write-Host "Args: $($forwardArgs -join ' ')"
    }
}

& $pythonExe $mainPy @forwardArgs
if ($LASTEXITCODE -ne 0) {
    throw "main.py failed with exit code $LASTEXITCODE"
}

$setter = Join-Path $scriptDir "set_geocentric_wallpaper.ps1"
if (-not (Test-Path $setter)) {
    throw "Wallpaper setter not found: $setter"
}

$imagePath = Join-Path $scriptDir "geocentric.png"
& $setter -ImagePath $imagePath
