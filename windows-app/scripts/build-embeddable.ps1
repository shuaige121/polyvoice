param(
    [string]$PythonVersion = "3.12.10",
    [string]$PythonZipUrl = "",
    [string]$PythonSpdxUrl = "",
    [string[]]$Packages = @(
        "sherpa-onnx",
        "sounddevice",
        "numpy",
        "pywin32",
        "PySide6",
        "requests",
        "jieba",
        "wordfreq"
    )
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

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
    $DistDir = Join-Path $AppRoot "dist"
    $CacheDir = Join-Path $DistDir "cache"
    $EmbedDir = Join-Path $DistDir "polyvoice-embed"
    $BinDir = Join-Path $EmbedDir "bin"
    $LibDir = Join-Path $EmbedDir "Lib"
    $SitePackagesDir = Join-Path $LibDir "site-packages"
    $SourceDir = Join-Path $AppRoot "polyvoice_app"

    if (-not $PythonZipUrl) {
        $PythonZipUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
    }
    if (-not $PythonSpdxUrl) {
        $PythonSpdxUrl = "$PythonZipUrl.spdx.json"
    }
    $PythonZipName = Split-Path $PythonZipUrl -Leaf
    $PythonZipPath = Join-Path $CacheDir $PythonZipName
    $GetPipPath = Join-Path $CacheDir "get-pip.py"
    $GetPipUrl = "https://bootstrap.pypa.io/get-pip.py"

    Write-Step "Preparing dist directories"
    New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null
    if (Test-Path $EmbedDir) {
        Remove-Item -Recurse -Force $EmbedDir
    }
    New-Item -ItemType Directory -Force -Path $BinDir, $SitePackagesDir | Out-Null

    Write-Step "Downloading CPython embeddable ZIP from python.org"
    Invoke-WebRequest -Uri $PythonZipUrl -OutFile $PythonZipPath

    Write-Step "Downloading CPython SPDX metadata for SHA256 verification"
    $SpdxJson = Invoke-RestMethod -Uri $PythonSpdxUrl
    $ExpectedSha = $null
    foreach ($Package in $SpdxJson.packages) {
        if ($Package.packageFileName -eq $PythonZipName -or $Package.downloadLocation -eq $PythonZipUrl) {
            foreach ($Checksum in $Package.checksums) {
                if ($Checksum.algorithm -eq "SHA256") {
                    $ExpectedSha = $Checksum.checksumValue
                }
            }
        }
    }
    if (-not $ExpectedSha) {
        Fail "Could not find SHA256 for $PythonZipName in $PythonSpdxUrl"
    }
    $ActualSha = (Get-FileHash -Algorithm SHA256 $PythonZipPath).Hash.ToLowerInvariant()
    if ($ActualSha -ne $ExpectedSha.ToLowerInvariant()) {
        Fail "CPython embeddable ZIP SHA256 mismatch. Expected $ExpectedSha, got $ActualSha"
    }

    Write-Step "Extracting CPython embeddable layout to dist/polyvoice-embed/bin"
    Expand-Archive -Path $PythonZipPath -DestinationPath $BinDir -Force

    Write-Step "Enabling site imports and app paths in python312._pth"
    $PthPath = Join-Path $BinDir "python312._pth"
    if (-not (Test-Path $PthPath)) {
        Fail "Expected $PthPath to exist after extracting Python $PythonVersion"
    }
    $PthLines = @(Get-Content $PthPath | Where-Object { $_ -notin @("..", "..\Lib\site-packages") })
    $PthLines = $PthLines | ForEach-Object {
        if ($_ -eq "#import site") { "import site" } else { $_ }
    }
    $ExtraLines = @("..", "..\Lib\site-packages")
    $ImportSiteIndex = [Array]::IndexOf($PthLines, "import site")
    if ($ImportSiteIndex -ge 0) {
        $BeforeImport = @()
        if ($ImportSiteIndex -gt 0) {
            $BeforeImport = @($PthLines[0..($ImportSiteIndex - 1)])
        }
        $AfterImport = @($PthLines[$ImportSiteIndex..($PthLines.Count - 1)])
        $PthLines = @($BeforeImport + $ExtraLines + $AfterImport)
    } else {
        $PthLines = @($PthLines + $ExtraLines + "import site")
    }
    Set-Content -Path $PthPath -Value $PthLines -Encoding ASCII

    Write-Step "Downloading get-pip.py"
    Invoke-WebRequest -Uri $GetPipUrl -OutFile $GetPipPath

    Write-Step "Installing pip into embedded Python"
    $PythonExe = Join-Path $BinDir "python.exe"
    & $PythonExe $GetPipPath --no-warn-script-location
    if ($LASTEXITCODE -ne 0) {
        Fail "get-pip.py failed with exit code $LASTEXITCODE"
    }

    Write-Step "Installing Python wheels into Lib/site-packages"
    & $PythonExe -m pip install --upgrade --no-cache-dir --target $SitePackagesDir @Packages
    if ($LASTEXITCODE -ne 0) {
        Fail "pip install failed with exit code $LASTEXITCODE"
    }

    Write-Step "Copying polyvoice_app source"
    Copy-Item -Path $SourceDir -Destination (Join-Path $EmbedDir "polyvoice_app") -Recurse -Force

    Write-Step "Writing polyvoice-launch.bat"
    $LaunchBat = Join-Path $EmbedDir "polyvoice-launch.bat"
    Set-Content -Path $LaunchBat -Encoding ASCII -Value @(
        "@echo off",
        "set ""APP_DIR=%~dp0""",
        "cd /d ""%APP_DIR%""",
        """%APP_DIR%bin\pythonw.exe"" -m polyvoice_app.main %*"
    )

    Write-Step "Embeddable app ready at $EmbedDir"
    exit 0
} catch {
    Write-Error $_
    exit 1
}
