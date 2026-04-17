param(
    [string]$EnvDir = ".conda-env",
    [string]$OutputDir = "dist\\conda-pack",
    [string]$ArchiveName = ""
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

    throw "Python executable not found under conda env: $Prefix"
}

$envPrefix = Resolve-LocalPath -PathValue $EnvDir
if (-not (Test-Path -LiteralPath (Join-Path $envPrefix "conda-meta"))) {
    throw "Conda env not found: $envPrefix. Run .\scripts\setup_backend_conda.ps1 first."
}

$null = Get-Command conda-pack -ErrorAction Stop

$pythonExe = Get-EnvPython -Prefix $envPrefix
$pythonVersion = (& $pythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
$outputRoot = Resolve-LocalPath -PathValue $OutputDir
New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null

if (-not $ArchiveName) {
    $ArchiveName = "construction-management-backend-conda-win-py$($pythonVersion.Replace('.', ''))-{0}.zip" -f (Get-Date -Format "yyyyMMdd-HHmmss")
}

$archivePath = Join-Path $outputRoot $ArchiveName

$previousNoPlugins = $env:CONDA_NO_PLUGINS
$env:CONDA_NO_PLUGINS = "true"
try {
    & conda-pack "-p" $envPrefix "-o" $archivePath "--force" | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "conda-pack failed for $envPrefix"
    }
} finally {
    if ($null -eq $previousNoPlugins) {
        Remove-Item Env:CONDA_NO_PLUGINS -ErrorAction SilentlyContinue
    } else {
        $env:CONDA_NO_PLUGINS = $previousNoPlugins
    }
}

Write-Host ""
Write-Host "Packed backend environment created:"
Write-Host $archivePath
Write-Host "Distribute this archive to teammates via NAS / shared drive / IM file transfer, not Git."
