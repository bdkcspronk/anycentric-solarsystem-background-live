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
$rotationStatePath = Join-Path $scriptDir "wallpaper_rotation_state.json"
$cycleCacheDir = Join-Path $scriptDir "wallpaper_cycle_cache"

$pythonExe = Join-Path $scriptDir ".venv\Scripts\python.exe"
$mainPy = Join-Path $scriptDir "main.py"

if (-not (Test-Path $pythonExe)) {
    throw "Python executable not found: $pythonExe"
}
if (-not (Test-Path $mainPy)) {
    throw "main.py not found: $mainPy"
}

$forwardArgs = @()
$cycleEnabled = $true
if (Test-Path $ConfigPath) {
    $cfg = Get-Content -Raw -Path $ConfigPath | ConvertFrom-Json
    if ($null -ne $cfg.main_args) {
        $forwardArgs = @($cfg.main_args)
    }
    if ($null -ne $cfg.cycle_enabled) {
        $cycleEnabled = [bool]$cfg.cycle_enabled
    }
}

if ($null -ne $MainArgs -and $MainArgs.Count -gt 0) {
    $forwardArgs = @($MainArgs)
}

# Support shorthand single-dash custom rotate flags in MainArgs, e.g. -Rotate.
$normalizedArgs = @()
for ($i = 0; $i -lt $forwardArgs.Count; $i++) {
    $a = [string]$forwardArgs[$i]
    if ($a -match "^(?i)-Rotate(?:X|Y|Z)?(?:=|$)") {
        $normalizedArgs += ("-" + $a)
    } else {
        $normalizedArgs += $a
    }
}
$forwardArgs = @($normalizedArgs)

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
                $next = [string]$ArgList[$i + 1]
                if (-not $next.StartsWith("--", [System.StringComparison]::Ordinal)) {
                    return $next
                }
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
            $i += 1
            if ($i -lt $ArgList.Count) {
                $next = [string]$ArgList[$i]
                if (-not $next.StartsWith("--", [System.StringComparison]::Ordinal)) {
                    $i += 1
                }
            }
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
            $i += 1
            if ($i -lt $ArgList.Count) {
                $next = [string]$ArgList[$i]
                if (-not $next.StartsWith("--", [System.StringComparison]::Ordinal)) {
                    $i += 1
                }
            }
            continue
        }
        $result += $a
        $i += 1
    }
    return @($result)
}

function Get-SelectionCycleGroups {
    param([string]$SelectionExpr)

    $exprForPy = if ($null -eq $SelectionExpr) { "" } else { $SelectionExpr }
    $code = @'
import json
import sys

script_dir = sys.argv[1]
expr = sys.argv[2] if len(sys.argv) > 2 else ''

sys.path.insert(0, script_dir)
import config


def split_top_level_or(expr: str) -> list[str]:
    text = str(expr or '').strip()
    if not text:
        return ['inner planets']

    tokens = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch in '()':
            tokens.append(ch)
            i += 1
            continue
        j = i
        while j < n and (not text[j].isspace()) and text[j] not in '()':
            j += 1
        tokens.append(text[i:j])
        i = j

    parts: list[list[str]] = [[]]
    depth = 0
    for t in tokens:
        lower = t.lower()
        if t == '(':
            depth += 1
            parts[-1].append(t)
            continue
        if t == ')':
            depth = max(0, depth - 1)
            parts[-1].append(t)
            continue
        if lower == "or" and depth == 0:
            parts.append([])
            continue
        parts[-1].append(t)

    out = []
    for p in parts:
        item = ' '.join(p).strip()
        if item:
            out.append(item)
    return out or ['inner planets']


groups = split_top_level_or(expr)

payload = []
for gexpr in groups:
    selected = set(config._evaluate_selection_expression(gexpr))
    ordered = [name for name in config.ALL_BODIES.keys() if name in selected]
    if 'sun' not in ordered:
        ordered.append('sun')
    payload.append({'expression': gexpr, 'bodies': ordered})

print(json.dumps(payload))
'@

    $tempPy = [System.IO.Path]::GetTempFileName()
    try {
        Set-Content -Path $tempPy -Value $code -Encoding UTF8
        $raw = & $pythonExe $tempPy $scriptDir $exprForPy
    } finally {
        Remove-Item -Path $tempPy -ErrorAction SilentlyContinue
    }
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($raw)) {
        return @()
    }
    try {
        return @($raw | ConvertFrom-Json)
    } catch {
        return @()
    }
}

function Get-NextCycledBodyFromGroups {
    param(
        [object[]]$Groups,
        [string]$SelectionKey,
        [string]$StatePath
    )
    if ($Groups.Count -eq 0) {
        return $null
    }

    $groupIdx = 0
    $bodyIdx = 0
    $savedKey = ""
    if (Test-Path $StatePath) {
        try {
            $state = Get-Content -Raw -Path $StatePath | ConvertFrom-Json
            if ($null -ne $state.group_index) { $groupIdx = [int]$state.group_index }
            if ($null -ne $state.body_index) { $bodyIdx = [int]$state.body_index }
            if ($null -ne $state.selection_key) { $savedKey = [string]$state.selection_key }
        } catch {
            $groupIdx = 0
            $bodyIdx = 0
            $savedKey = ""
        }
    }

    if (-not $savedKey.Equals($SelectionKey, [System.StringComparison]::Ordinal)) {
        $groupIdx = 0
        $bodyIdx = 0
    }

    $groupCount = $Groups.Count
    $result = $null
    for ($guard = 0; $guard -lt $groupCount; $guard++) {
        $groupIdx = (($groupIdx % $groupCount) + $groupCount) % $groupCount
        $group = $Groups[$groupIdx]
        $bodies = @($group.bodies)
        if ($bodies.Count -eq 0) {
            $groupIdx = ($groupIdx + 1) % $groupCount
            $bodyIdx = 0
            continue
        }

        $bodyIdx = (($bodyIdx % $bodies.Count) + $bodies.Count) % $bodies.Count
        $body = [string]$bodies[$bodyIdx]

        $nextGroupIdx = $groupIdx
        $nextBodyIdx = $bodyIdx + 1
        if ($nextBodyIdx -ge $bodies.Count) {
            $nextBodyIdx = 0
            $nextGroupIdx = ($groupIdx + 1) % $groupCount
        }

        @{
            selection_key = $SelectionKey
            group_index = $nextGroupIdx
            body_index = $nextBodyIdx
        } | ConvertTo-Json | Set-Content -Path $StatePath -Encoding UTF8

        $result = @{
            body = $body
            expression = [string]$group.expression
            group_index = $groupIdx
            group_count = $groupCount
        }
        break
    }

    return $result
}

function Parse-DoubleOrThrow {
    param(
        [string]$Value,
        [string]$Name
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return 0.0
    }

    $num = 0.0
    if ([double]::TryParse($Value, [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$num)) {
        return $num
    }
    throw "Invalid numeric value for --${Name}: '$Value'"
}

function Wrap-Degrees {
    param([double]$Angle)
    $wrapped = $Angle % 360.0
    if ($wrapped -lt 0.0) {
        $wrapped += 360.0
    }
    return $wrapped
}

function Get-RotationState {
    param(
        [string]$StatePath,
        [double]$DefaultYaw,
        [double]$DefaultPitch,
        [double]$DefaultRoll
    )

    $state = @{
        yaw = Wrap-Degrees -Angle $DefaultYaw
        pitch = Wrap-Degrees -Angle $DefaultPitch
        roll = Wrap-Degrees -Angle $DefaultRoll
    }

    if (Test-Path $StatePath) {
        try {
            $loaded = Get-Content -Raw -Path $StatePath | ConvertFrom-Json
            if ($null -ne $loaded.yaw) { $state.yaw = Wrap-Degrees -Angle ([double]$loaded.yaw) }
            if ($null -ne $loaded.pitch) { $state.pitch = Wrap-Degrees -Angle ([double]$loaded.pitch) }
            if ($null -ne $loaded.roll) { $state.roll = Wrap-Degrees -Angle ([double]$loaded.roll) }
        } catch {
            # Keep defaults when state file is missing or invalid.
        }
    }

    return $state
}

function Save-RotationState {
    param(
        [string]$StatePath,
        [double]$Yaw,
        [double]$Pitch,
        [double]$Roll
    )

    @{
        yaw = Wrap-Degrees -Angle $Yaw
        pitch = Wrap-Degrees -Angle $Pitch
        roll = Wrap-Degrees -Angle $Roll
    } | ConvertTo-Json | Set-Content -Path $StatePath -Encoding UTF8
}

function Get-ArgsSignature {
    param([string[]]$ArgList)
    return (($ArgList | ForEach-Object { [string]$_ }) -join "`n")
}

function Get-BodyCacheSlug {
    param([string]$BodyName)
    $text = if ($null -eq $BodyName) { "" } else { $BodyName }
    return ($text.ToLowerInvariant() -replace "[^a-z0-9_-]", "_")
}

# Cycle center body inside the effective selection unless center body is explicitly provided.
if ($cycleEnabled -and -not (Test-HasArg -ArgList $forwardArgs -Name "center-body")) {
    $selectionExpr = Get-ArgValue -ArgList $forwardArgs -Name "selection"
    if ([string]::IsNullOrWhiteSpace($selectionExpr)) {
        $selectionExpr = "inner planets"
    }

    $cycleGroups = Get-SelectionCycleGroups -SelectionExpr $selectionExpr
    $flat = @()
    for ($gi = 0; $gi -lt $cycleGroups.Count; $gi++) {
        $g = $cycleGroups[$gi]
        $flat += ("g=$gi|e=" + [string]$g.expression + "|b=" + (@($g.bodies) -join ","))
    }
    $selectionKey = "$selectionExpr|$($flat -join ';')"
    $nextCycle = Get-NextCycledBodyFromGroups -Groups $cycleGroups -SelectionKey $selectionKey -StatePath $cycleStatePath
    if ($null -ne $nextCycle -and -not [string]::IsNullOrWhiteSpace([string]$nextCycle.body)) {
        $activeExpr = [string]$nextCycle.expression
        $nextBody = [string]$nextCycle.body

        # Always use the active group expression for this cycle step.
        $forwardArgs = @(Remove-Arg -ArgList $forwardArgs -Name "selection")
        if ($nextBody.Equals("sun", [System.StringComparison]::OrdinalIgnoreCase)) {
            # main.py requires center body to be explicitly included by selection expression.
            $activeExpr = "($activeExpr) OR sun"
        }
        $forwardArgs = @($forwardArgs + @("--selection", $activeExpr))
        $forwardArgs = @($forwardArgs + @("--center-body=$nextBody"))

        if ($VerboseLog) {
            $groupDisplay = ([int]$nextCycle.group_index + 1)
            $groupCount = [int]$nextCycle.group_count
            Write-Host "Cycle group: $groupDisplay/$groupCount"
            Write-Host "Cycle expression: $activeExpr"
            Write-Host "Cycle center-body: $nextBody"
        }
    }
}

$rotateZStep = Parse-DoubleOrThrow -Value (Get-ArgValue -ArgList $forwardArgs -Name "RotateZ") -Name "RotateZ"
$rotateYStep = Parse-DoubleOrThrow -Value (Get-ArgValue -ArgList $forwardArgs -Name "RotateY") -Name "RotateY"
$rotateXStep = Parse-DoubleOrThrow -Value (Get-ArgValue -ArgList $forwardArgs -Name "RotateX") -Name "RotateX"
$rotateRandom = Test-HasArg -ArgList $forwardArgs -Name "Rotate"

$forwardArgs = @(Remove-Arg -ArgList $forwardArgs -Name "RotateZ")
$forwardArgs = @(Remove-Arg -ArgList $forwardArgs -Name "RotateY")
$forwardArgs = @(Remove-Arg -ArgList $forwardArgs -Name "RotateX")
$forwardArgs = @(Remove-Arg -ArgList $forwardArgs -Name "Rotate")

$hasRotateStep = ($rotateZStep -ne 0.0) -or ($rotateYStep -ne 0.0) -or ($rotateXStep -ne 0.0)
if ($rotateRandom -or $hasRotateStep) {
    $baseYaw = Parse-DoubleOrThrow -Value (Get-ArgValue -ArgList $forwardArgs -Name "yaw") -Name "yaw"
    $basePitch = Parse-DoubleOrThrow -Value (Get-ArgValue -ArgList $forwardArgs -Name "pitch") -Name "pitch"
    $baseRoll = Parse-DoubleOrThrow -Value (Get-ArgValue -ArgList $forwardArgs -Name "roll") -Name "roll"
    $rotation = Get-RotationState -StatePath $rotationStatePath -DefaultYaw $baseYaw -DefaultPitch $basePitch -DefaultRoll $baseRoll

    if ($rotateRandom) {
        $rotation.yaw = Get-Random -Minimum 0.0 -Maximum 360.0
        $rotation.pitch = Get-Random -Minimum 0.0 -Maximum 360.0
        $rotation.roll = Get-Random -Minimum 0.0 -Maximum 360.0
    } else {
        # Axis mapping follows the existing renderer conventions:
        # yaw=z, pitch=x, roll=y.
        $rotation.yaw = Wrap-Degrees -Angle ($rotation.yaw + $rotateZStep)
        $rotation.pitch = Wrap-Degrees -Angle ($rotation.pitch + $rotateXStep)
        $rotation.roll = Wrap-Degrees -Angle ($rotation.roll + $rotateYStep)
    }

    $forwardArgs = @(Set-ArgValue -ArgList $forwardArgs -Name "yaw" -Value ([string]::Format([System.Globalization.CultureInfo]::InvariantCulture, "{0:0.######}", $rotation.yaw)))
    $forwardArgs = @(Set-ArgValue -ArgList $forwardArgs -Name "pitch" -Value ([string]::Format([System.Globalization.CultureInfo]::InvariantCulture, "{0:0.######}", $rotation.pitch)))
    $forwardArgs = @(Set-ArgValue -ArgList $forwardArgs -Name "roll" -Value ([string]::Format([System.Globalization.CultureInfo]::InvariantCulture, "{0:0.######}", $rotation.roll)))
    Save-RotationState -StatePath $rotationStatePath -Yaw $rotation.yaw -Pitch $rotation.pitch -Roll $rotation.roll
}

$effectiveCenterBody = Get-ArgValue -ArgList $forwardArgs -Name "center-body"
$cycleCacheEnabled = $cycleEnabled -and -not $rotateRandom -and -not $hasRotateStep -and -not [string]::IsNullOrWhiteSpace($effectiveCenterBody)
$cacheHitImagePath = $null
$cacheImagePath = $null
$cacheMetaPath = $null
$argsSignature = ""

if ($cycleCacheEnabled) {
    $argsSignature = Get-ArgsSignature -ArgList $forwardArgs
    $bodySlug = Get-BodyCacheSlug -BodyName $effectiveCenterBody
    $cacheImagePath = Join-Path $cycleCacheDir ("{0}.png" -f $bodySlug)
    $cacheMetaPath = Join-Path $cycleCacheDir ("{0}.json" -f $bodySlug)

    if ((Test-Path $cacheImagePath) -and (Test-Path $cacheMetaPath)) {
        try {
            $cacheMeta = Get-Content -Raw -Path $cacheMetaPath | ConvertFrom-Json
            if ($null -ne $cacheMeta.signature -and [string]$cacheMeta.signature -eq $argsSignature) {
                $cacheHitImagePath = $cacheImagePath
            }
        } catch {
            $cacheHitImagePath = $null
        }
    }
}

if ($VerboseLog) {
    Write-Host "Running wallpaper generation..."
    Write-Host "Python: $pythonExe"
    Write-Host "Script: $mainPy"
    Write-Host "Cycle enabled: $cycleEnabled"
    if ($rotateRandom) {
        Write-Host "Rotation mode: random"
    } elseif ($hasRotateStep) {
        Write-Host "Rotation step: Z(yaw)=$rotateZStep Y(roll)=$rotateYStep X(pitch)=$rotateXStep"
    }
    if ($cycleCacheEnabled) {
        if ($null -ne $cacheHitImagePath) {
            Write-Host "Cycle cache: hit for center-body '$effectiveCenterBody'"
        } else {
            Write-Host "Cycle cache: miss for center-body '$effectiveCenterBody'"
        }
    }
    if ($forwardArgs.Count -gt 0) {
        Write-Host "Args: $($forwardArgs -join ' ')"
    }
}

$imagePath = Join-Path $scriptDir "wallpaper.png"
if ($null -eq $cacheHitImagePath) {
    $pythonArgs = @($forwardArgs)
    if ($VerboseLog) {
        $pythonArgs += "--verbose-log"
    }
    & $pythonExe $mainPy @pythonArgs
    if ($LASTEXITCODE -ne 0) {
        throw "main.py failed with exit code $LASTEXITCODE"
    }

    if ($cycleCacheEnabled -and -not [string]::IsNullOrWhiteSpace($cacheImagePath) -and -not [string]::IsNullOrWhiteSpace($cacheMetaPath)) {
        if (-not (Test-Path $cycleCacheDir)) {
            New-Item -Path $cycleCacheDir -ItemType Directory -Force | Out-Null
        }
        Copy-Item -Path $imagePath -Destination $cacheImagePath -Force
        @{
            center_body = $effectiveCenterBody
            signature = $argsSignature
            updated_utc = (Get-Date).ToUniversalTime().ToString("o")
        } | ConvertTo-Json | Set-Content -Path $cacheMetaPath -Encoding UTF8

        # Set wallpaper from the cache file so the active image always matches cache content.
        $imagePath = $cacheImagePath
    }
} else {
    # Cached image already matches the exact forwarded arguments.
    $imagePath = $cacheHitImagePath
}

$setter = Join-Path $scriptDir "set_wallpaper.ps1"
if (-not (Test-Path $setter)) {
    throw "Wallpaper setter not found: $setter"
}

& $setter -ImagePath $imagePath
