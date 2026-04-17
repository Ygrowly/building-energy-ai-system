param(
    [switch]$IncludeForecast,
    [switch]$Recreate,
    [switch]$SkipPipUpgrade
)

$ErrorActionPreference = "Stop"

$backendDir = Split-Path -Parent $PSScriptRoot
Set-Location $backendDir

function Get-PythonBootstrapCommand {
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        try {
            $python311Path = (& py -3.11 -c "import sys; print(sys.executable)").Trim()
            if ($python311Path -and (Test-Path -LiteralPath $python311Path)) {
                return @{
                    Exe  = $python311Path
                    Args = @()
                    Name = $python311Path
                }
            }
        } catch {
        }
    }

    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        return @{
            Exe  = $pythonCmd.Source
            Args = @()
            Name = $pythonCmd.Source
        }
    }

    throw "Python was not found. Install Python 3.11+ first."
}

function Ensure-PipAvailable {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PythonExe
    )

    & $PythonExe -m pip --version | Out-Null
    if ($LASTEXITCODE -eq 0) {
        return
    }

    Write-Host "Bootstrapping pip"
    & $PythonExe -Im ensurepip --default-pip | Out-Host
    if ($LASTEXITCODE -eq 0) {
        return
    }

    & $PythonExe -m pip --version | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "pip is not available in $PythonExe"
    }
}

function Invoke-BootstrapPython {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Command,
        [Parameter(Mandatory = $true)]
        [string[]]$Args
    )

    & $Command.Exe @($Command.Args + $Args) | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Bootstrap Python command failed: $($Command.Name) $($Args -join ' ')"
    }
}

function Install-Venv {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$RequirementsFile,
        [Parameter(Mandatory = $true)]
        [hashtable]$BootstrapCommand
    )

    $venvDir = Join-Path $backendDir $Name
    $venvPython = Join-Path $venvDir "Scripts\python.exe"

    if ($Recreate -and (Test-Path -LiteralPath $venvDir)) {
        Remove-Item -Recurse -Force -LiteralPath $venvDir
    }

    if (-not (Test-Path -LiteralPath $venvPython)) {
        Write-Host "Creating virtual environment: $Name"
        Invoke-BootstrapPython -Command $BootstrapCommand -Args @("-m", "venv", "--without-pip", $venvDir)
    } else {
        Write-Host "Virtual environment already exists: $Name"
    }

    Ensure-PipAvailable -PythonExe $venvPython

    if (-not $SkipPipUpgrade) {
        Write-Host "Upgrading pip tooling in $Name"
        & $venvPython -m pip install --upgrade pip setuptools wheel | Out-Host
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Retrying pip tooling upgrade with --ignore-installed"
            & $venvPython -m pip install --upgrade --ignore-installed pip setuptools wheel | Out-Host
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to upgrade pip tooling in $Name"
            }
        }
    }

    Write-Host "Installing dependencies from $RequirementsFile"
    & $venvPython -m pip install -r (Join-Path $backendDir $RequirementsFile) | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install dependencies from $RequirementsFile"
    }

    Write-Host "Ready: $venvPython"
    return $venvPython
}

$bootstrap = Get-PythonBootstrapCommand
Write-Host "Using bootstrap interpreter: $($bootstrap.Name)"

$mainPython = Install-Venv -Name ".venv" -RequirementsFile "requirements.txt" -BootstrapCommand $bootstrap

if ($IncludeForecast) {
    Install-Venv -Name ".venv-forecast" -RequirementsFile "requirements-forecast.txt" -BootstrapCommand $bootstrap | Out-Null
}

Write-Host ""
Write-Host "Backend environment is ready."
Write-Host "Main Python: $mainPython"
if ($IncludeForecast) {
    Write-Host "Forecast Python: $(Join-Path $backendDir '.venv-forecast\Scripts\python.exe')"
}
Write-Host "Start backend with: powershell -ExecutionPolicy Bypass -File .\scripts\run_backend.ps1"
