param(
    [string]$EnvDir = ".conda-env",
    [string]$PythonVersion = "3.11",
    [string]$CloneFrom = "",
    [switch]$IncludeForecast,
    [switch]$Recreate,
    [switch]$SkipPipUpgrade,
    [switch]$UpgradePipTooling
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

function Invoke-CondaCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Args
    )

    $previousCudaOverride = $env:CONDA_OVERRIDE_CUDA
    $env:CONDA_OVERRIDE_CUDA = "0"
    try {
        & conda "--no-plugins" @Args | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "Conda command failed: conda --no-plugins $($Args -join ' ')"
        }
    } finally {
        if ($null -eq $previousCudaOverride) {
            Remove-Item Env:CONDA_OVERRIDE_CUDA -ErrorAction SilentlyContinue
        } else {
            $env:CONDA_OVERRIDE_CUDA = $previousCudaOverride
        }
    }
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

if ($Recreate -and (Test-Path -LiteralPath $envPrefix)) {
    Remove-Item -Recurse -Force -LiteralPath $envPrefix
}

$condaMetaDir = Join-Path $envPrefix "conda-meta"
if (-not (Test-Path -LiteralPath $condaMetaDir)) {
    if ($CloneFrom) {
        Write-Host "Cloning local conda environment '$CloneFrom' to: $envPrefix"
        Invoke-CondaCommand -Args @(
            "create",
            "--yes",
            "--solver",
            "classic",
            "--prefix",
            $envPrefix,
            "--clone",
            $CloneFrom
        )
    } else {
        Write-Host "Creating conda environment: $envPrefix"
        try {
            Invoke-CondaCommand -Args @(
                "create",
                "--yes",
                "--solver",
                "classic",
                "--prefix",
                $envPrefix,
                "python=$PythonVersion",
                "pip"
            )
        } catch {
            throw "Failed to create a fresh conda env. If this machine also has conda SSL issues, retry with -CloneFrom <existing_conda_env>."
        }
    }
} else {
    Write-Host "Conda environment already exists: $envPrefix"
}

$pythonExe = Get-EnvPython -Prefix $envPrefix

if ($UpgradePipTooling -and -not $SkipPipUpgrade) {
    Write-Host "Upgrading pip tooling"
    & $pythonExe -m pip install --upgrade pip setuptools wheel | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to upgrade pip tooling in $envPrefix"
    }
} else {
    Write-Host "Keeping conda-managed pip/setuptools/wheel versions for conda-pack compatibility"
}

Write-Host "Installing backend requirements"
& $pythonExe -m pip install -r (Join-Path $backendDir "requirements.txt") | Out-Host
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install backend requirements"
}

if ($IncludeForecast) {
    Write-Host "Installing forecast requirements"
    & $pythonExe -m pip install -r (Join-Path $backendDir "requirements-forecast.txt") | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install forecast requirements"
    }
}

Write-Host ""
Write-Host "Conda backend environment is ready."
Write-Host "Env prefix: $envPrefix"
Write-Host "Python: $pythonExe"
Write-Host "Start backend with: powershell -ExecutionPolicy Bypass -File .\scripts\run_backend.ps1 -EnvDir $EnvDir"
