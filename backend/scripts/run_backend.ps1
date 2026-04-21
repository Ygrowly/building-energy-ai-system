param(
    [string]$PythonExe = "",
    [string]$EnvDir = "",
    [string]$BindHost = "0.0.0.0",
    [int]$Port = 8000,
    [switch]$NoReload
)

$ErrorActionPreference = "Stop"

$backendDir = Split-Path -Parent $PSScriptRoot

function Resolve-BackendPython {
    param(
        [string]$ExplicitPythonExe,
        [string]$ExplicitEnvDir
    )

    if ($ExplicitPythonExe) {
        $resolvedPython = if ([System.IO.Path]::IsPathRooted($ExplicitPythonExe)) {
            $ExplicitPythonExe
        } else {
            Join-Path $backendDir $ExplicitPythonExe
        }
        if (-not (Test-Path -LiteralPath $resolvedPython)) {
            throw "Python executable not found: $resolvedPython"
        }
        return $resolvedPython
    }

    $candidateDirs = @()
    if ($ExplicitEnvDir) {
        $candidateDirs += if ([System.IO.Path]::IsPathRooted($ExplicitEnvDir)) {
            $ExplicitEnvDir
        } else {
            Join-Path $backendDir $ExplicitEnvDir
        }
    } else {
        $candidateDirs += @(
            (Join-Path $backendDir ".conda-packed-env"),
            (Join-Path $backendDir ".conda-env"),
            (Join-Path $backendDir ".venv")
        )
    }

    foreach ($dir in $candidateDirs) {
        foreach ($candidate in @(
            (Join-Path $dir "python.exe"),
            (Join-Path $dir "Scripts\python.exe")
        )) {
            if (Test-Path -LiteralPath $candidate) {
                return $candidate
            }
        }
    }

    throw "No backend Python runtime found. Expected .conda-packed-env, .conda-env, or .venv. Run the corresponding setup script first."
}

$runtimePython = Resolve-BackendPython -ExplicitPythonExe $PythonExe -ExplicitEnvDir $EnvDir

Set-Location $backendDir

$args = @(
    "-m",
    "uvicorn",
    "main:app",
    "--host",
    $BindHost,
    "--port",
    "$Port"
)

if (-not $NoReload) {
    $args += "--reload"
}

& $runtimePython @args
if ($LASTEXITCODE -ne 0) {
    throw "Backend startup failed."
}
