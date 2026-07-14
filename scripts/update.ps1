# Pull the latest code from GitHub and relaunch the backstage stack.
# Run from anywhere:  powershell -ExecutionPolicy Bypass -File scripts\update.ps1

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

Write-Host "Updating from GitHub..."
git pull --ff-only
if ($LASTEXITCODE -ne 0) {
    Write-Host "git pull failed — resolve manually, then rerun." -ForegroundColor Red
    exit 1
}

& "$PSScriptRoot\start-backstage.ps1"
