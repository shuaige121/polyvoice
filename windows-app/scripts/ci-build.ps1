param(
    [string]$PythonVersion = "3.12.10",
    [string]$PythonZipUrl = "",
    [string]$PythonSpdxUrl = "",
    [string]$MakensisPath = "makensis"
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message"
}

function Fail {
    param([string]$Message)
    Write-Error $Message
    exit 1
}

try {
    $AppRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
    $InstallerScript = Join-Path $PSScriptRoot "make-installer.nsi"
    $BuildScript = Join-Path $PSScriptRoot "build-embeddable.ps1"

    Write-Step "Building embeddable Python app"
    $BuildArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $BuildScript, "-PythonVersion", $PythonVersion)
    if ($PythonZipUrl) {
        $BuildArgs += @("-PythonZipUrl", $PythonZipUrl)
    }
    if ($PythonSpdxUrl) {
        $BuildArgs += @("-PythonSpdxUrl", $PythonSpdxUrl)
    }
    & pwsh @BuildArgs
    if ($LASTEXITCODE -ne 0) {
        Fail "build-embeddable.ps1 failed with exit code $LASTEXITCODE"
    }

    Write-Step "Checking NSIS availability"
    $MakensisCommand = Get-Command $MakensisPath -ErrorAction SilentlyContinue
    if (-not $MakensisCommand) {
        Fail @"
NSIS makensis was not found.

Install one of:
  scoop install nsis
  choco install nsis

Then re-run:
  pwsh scripts\ci-build.ps1
"@
    }

    Write-Step "Running makensis"
    Push-Location $AppRoot
    try {
        & $MakensisCommand.Source $InstallerScript
        if ($LASTEXITCODE -ne 0) {
            Fail "makensis failed with exit code $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }

    Write-Step "Installer ready at $(Join-Path $AppRoot 'dist\polyvoice-installer-v0.1.exe')"
    exit 0
} catch {
    Write-Error $_
    exit 1
}
