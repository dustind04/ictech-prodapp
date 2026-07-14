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

# Reuse a previously pinned port; otherwise probe: 80 first (TV URLs
# need no port), then 8080 upward. 8058 is always mapped separately,
# so it's excluded from the probe.
$envText = Get-Content ".env" -Raw
$pinned = [regex]::Match($envText, "(?m)^ICTECH_PORT=(\d+)").Groups[1].Value
if ($pinned) {
    $port = [int]$pinned
} else {
    $candidates = @(80) + (8080..8098)
    $port = $null
    foreach ($try in $candidates) {
        try {
            $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Any, $try)
            $listener.Start(); $listener.Stop()
            $port = $try
            break
        } catch {
            Write-Host "Port $try is in use, trying next..."
        }
    }
    if (-not $port) { Write-Host "No free port found (80, 8080..8098)" -ForegroundColor Red; exit 1 }
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
$p = if ($port -eq 80) { "" } else { ":$port" }
$hostname = $env:COMPUTERNAME.ToLower()
Write-Host ""
Write-Host "icTech is up (build $($env:GIT_SHA)):" -ForegroundColor Green
Write-Host "  TV setup page    http://${ip}$p/tv   (big buttons - easiest for TVs)"
Write-Host "  Dashboard        http://${ip}$p/"
Write-Host "  Simple Micboard  http://${ip}$p/mb"
Write-Host "  Tech dashboard   http://${ip}$p/tech"
Write-Host "  Admin            http://${ip}$p/admin"
Write-Host ""
Write-Host "  By name (if this PC's name resolves on your network):"
Write-Host "  http://$hostname$p/tv    or    http://$hostname.local$p/tv"
