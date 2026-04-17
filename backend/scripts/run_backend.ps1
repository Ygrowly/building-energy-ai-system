param(
    [string]$Host = "0.0.0.0",
    [int]$Port = 8000,
    [switch]$NoReload
)

$ErrorActionPreference = "Stop"

$backendDir = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $backendDir ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "Missing backend virtual environment: $venvPython. Run .\scripts\setup_backend_venv.ps1 first."
}

Set-Location $backendDir

$args = @(
    "-m",
    "uvicorn",
    "main:app",
    "--host",
    $Host,
    "--port",
    "$Port"
)

if (-not $NoReload) {
    $args += "--reload"
}

& $venvPython @args
if ($LASTEXITCODE -ne 0) {
    throw "Backend startup failed."
}
