# Builds dist\VideoBatchDownloader.exe (single-file, windowed).
# Add -Installer to also produce dist\VideoBatchDownloader-<version>-setup.exe
# with Inno Setup.
#
# Usage: .\build.ps1 [-Installer]   (requires uv; installs the dev group on first run)
param([switch]$Installer)

Set-Location $PSScriptRoot

# Native tools here write progress to stderr, which Windows PowerShell turns
# into terminating errors under "Stop". Check exit codes explicitly instead.
$ErrorActionPreference = "Continue"

function Invoke-Step {
    param([string]$Exe, [string[]]$Arguments, [string]$What)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        Write-Host "$What failed with exit code $LASTEXITCODE" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

Invoke-Step "uv" @("sync", "--group", "dev") "uv sync"
if (Test-Path build) { Remove-Item build -Recurse -Force }
Invoke-Step "uv" @("run", "pyinstaller", "VideoBatchDownloader.spec", "--noconfirm", "--clean") "PyInstaller"

$exe = Join-Path $PSScriptRoot "dist\VideoBatchDownloader.exe"
if (-not (Test-Path $exe)) { Write-Host "Build failed: $exe not found" -ForegroundColor Red; exit 1 }
Write-Host ("Built {0} ({1} MB)" -f $exe, [math]::Round((Get-Item $exe).Length / 1MB, 1)) -ForegroundColor Green

if (-not $Installer) { return }

$iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
    $iscc = @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $iscc) {
    Write-Host "Inno Setup (ISCC.exe) not found. Install it from https://jrsoftware.org/isdl.php" -ForegroundColor Red
    exit 1
}

Invoke-Step $iscc @("/Q", (Join-Path $PSScriptRoot "installer.iss")) "Inno Setup"

$setup = Get-ChildItem (Join-Path $PSScriptRoot "dist") -Filter "*-setup.exe" |
         Sort-Object LastWriteTime -Descending | Select-Object -First 1
Write-Host ("Built {0} ({1} MB)" -f $setup.FullName, [math]::Round($setup.Length / 1MB, 1)) -ForegroundColor Green
