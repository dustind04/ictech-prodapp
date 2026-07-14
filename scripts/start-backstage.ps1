# Launch (or relaunch) the backstage stack on Docker Desktop.
#   - finds a free host port starting at 8058 and pins it in .env
#     (once chosen, the port is kept on every future start so the TVs'
#     bookmarked URLs never move)
#   - stamps the build with the current git commit for the in-app
#     update check
# Run from the repo root:  powershell -ExecutionPolicy Bypass -File scripts\start-backstage.ps1

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not (Test-Path ".env")) {
    Write-Host "No .env found — copy .env.example to .env and set the secrets first." -ForegroundColor Red
    exit 1
}

# Reuse a previously pinned port; otherwise probe for a free one.
$envText = Get-Content ".env" -Raw
$pinned = [regex]::Match($envText, "(?m)^ICTECH_PORT=(\d+)").Groups[1].Value
if ($pinned) {
    $port = [int]$pinned
} else {
    $port = 8058
    while ($true) {
        $listener = $null
        try {
            $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Any, $port)
            $listener.Start(); $listener.Stop()
            break
        } catch {
            Write-Host "Port $port is in use, trying $($port + 1)..."
            $port++
            if ($port -gt 8078) { Write-Host "No free port in 8058..8078" -ForegroundColor Red; exit 1 }
        }
    }
    Add-Content ".env" "`nICTECH_PORT=$port"
    Write-Host "Pinned host port $port in .env"
}

$env:ICTECH_PORT = "$port"
$env:GIT_SHA = (git rev-parse --short HEAD).Trim()

docker compose -f docker-compose.backstage.yaml up -d --build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$ip = (Get-NetIPAddress -AddressFamily IPv4 |
       Where-Object { $_.IPAddress -notlike "169.254*" -and $_.IPAddress -ne "127.0.0.1" } |
       Select-Object -First 1).IPAddress
Write-Host ""
Write-Host "icTech is up (build $($env:GIT_SHA)):" -ForegroundColor Green
Write-Host "  Dashboard        http://${ip}:$port/"
Write-Host "  Simple Micboard  http://${ip}:$port/micboard"
Write-Host "  Tech dashboard   http://${ip}:$port/techdashboard"
Write-Host "  Admin            http://${ip}:$port/admin"
