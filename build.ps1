# Builds dist\VideoBatchDownloader.exe (single-file, windowed).
# Usage: .\build.ps1   (requires uv; installs the dev group on first run)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
uv sync --group dev
if (Test-Path build) { Remove-Item build -Recurse -Force }
uv run pyinstaller VideoBatchDownloader.spec --noconfirm --clean
$exe = Join-Path $PSScriptRoot "dist\VideoBatchDownloader.exe"
if (Test-Path $exe) {
    $mb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
    Write-Host "Built $exe ($mb MB)"
} else {
    Write-Error "Build failed: $exe not found"
}
