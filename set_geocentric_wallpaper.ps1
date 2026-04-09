[CmdletBinding(SupportsShouldProcess=$true)]
param(
    [string]$ImagePath = "geocentric.png"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not [System.IO.Path]::IsPathRooted($ImagePath)) {
    $ImagePath = Join-Path $scriptDir $ImagePath
}

if (-not (Test-Path $ImagePath)) {
    throw "Wallpaper image not found: $ImagePath"
}

$resolvedImagePath = (Resolve-Path $ImagePath).Path

# Fill style (works for most displays):
# WallpaperStyle=10, TileWallpaper=0
Set-ItemProperty -Path "HKCU:\Control Panel\Desktop" -Name WallpaperStyle -Value "10"
Set-ItemProperty -Path "HKCU:\Control Panel\Desktop" -Name TileWallpaper -Value "0"

$signature = @"
using System;
using System.Runtime.InteropServices;
public static class WallpaperApi {
    [DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    public static extern bool SystemParametersInfo(int uAction, int uParam, string lpvParam, int fuWinIni);
}
"@

if (-not ("WallpaperApi" -as [type])) {
    Add-Type -TypeDefinition $signature | Out-Null
}

$SPI_SETDESKWALLPAPER = 20
$SPIF_UPDATEINIFILE = 0x01
$SPIF_SENDWININICHANGE = 0x02
$flags = $SPIF_UPDATEINIFILE -bor $SPIF_SENDWININICHANGE

if ($PSCmdlet.ShouldProcess($resolvedImagePath, "Set desktop wallpaper")) {
    $ok = [WallpaperApi]::SystemParametersInfo($SPI_SETDESKWALLPAPER, 0, $resolvedImagePath, $flags)
    if (-not $ok) {
        throw "Failed to set wallpaper via SystemParametersInfo."
    }
    Write-Host "Wallpaper updated: $resolvedImagePath"
}
