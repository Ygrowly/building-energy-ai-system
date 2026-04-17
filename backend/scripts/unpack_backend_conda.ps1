param(
    [string]$Archive = "",
    [string]$TargetDir = ".conda-packed-env",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$backendDir = Split-Path -Parent $PSScriptRoot
Set-Location $backendDir

function Resolve-LocalPath {
    param([string]$PathValue)

    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return $PathValue
    }
    return (Join-Path $backendDir $PathValue)
}

function Get-EnvPython {
    param([string]$Prefix)

    foreach ($candidate in @(
        (Join-Path $Prefix "python.exe"),
        (Join-Path $Prefix "Scripts\python.exe")
    )) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }

    throw "Python executable not found under packed env: $Prefix"
}

function Find-CondaUnpackCommand {
    param([string]$Prefix)

    foreach ($candidate in @(
        (Join-Path $Prefix "Scripts\conda-unpack.exe"),
        (Join-Path $Prefix "Scripts\conda-unpack-script.py"),
        (Join-Path $Prefix "Scripts\conda-unpack")
    )) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }

    return ""
}

$archivePath = ""
if ($Archive) {
    $archivePath = Resolve-LocalPath -PathValue $Archive
} else {
    $defaultPackDir = Resolve-LocalPath -PathValue "dist\\conda-pack"
    $latestArchive = Get-ChildItem -Path $defaultPackDir -Filter *.zip -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($latestArchive) {
        $archivePath = $latestArchive.FullName
    }
}

if (-not $archivePath -or -not (Test-Path -LiteralPath $archivePath)) {
    throw "Packed backend archive not found. Provide -Archive or place a zip under backend\\dist\\conda-pack."
}

$targetPath = Resolve-LocalPath -PathValue $TargetDir
if (Test-Path -LiteralPath $targetPath) {
    if (-not $Force) {
        throw "Target directory already exists: $targetPath. Use -Force to replace it."
    }
    Remove-Item -Recurse -Force -LiteralPath $targetPath
}

Write-Host "Extracting archive to $targetPath"
Expand-Archive -LiteralPath $archivePath -DestinationPath $targetPath -Force

$pythonExe = Get-EnvPython -Prefix $targetPath
$condaUnpack = Find-CondaUnpackCommand -Prefix $targetPath

if (-not $condaUnpack) {
    throw "conda-unpack command not found after extraction. Rebuild the archive with conda-pack."
}

Write-Host "Rewriting packed environment prefixes"
if ($condaUnpack.EndsWith(".py")) {
    & $pythonExe $condaUnpack | Out-Host
} else {
    & $condaUnpack | Out-Host
}
if ($LASTEXITCODE -ne 0) {
    throw "conda-unpack failed."
}

Write-Host ""
Write-Host "Packed backend environment is ready."
Write-Host "Env prefix: $targetPath"
Write-Host "Python: $pythonExe"
Write-Host "Start backend with: powershell -ExecutionPolicy Bypass -File .\scripts\run_backend.ps1 -EnvDir $TargetDir"
