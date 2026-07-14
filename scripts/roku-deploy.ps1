# Package the icTech Roku channel and sideload it to every Roku on the
# LAN (or the ones you name). One-time per TV first: enable Developer
# Mode (Home x3, Up x2, Right, Left, Right, Left, Right), note the
# password you set, accept the SDK agreement.
#
#   powershell -ExecutionPolicy Bypass -File scripts\roku-deploy.ps1 -Password <devpass>
#   ... -Devices 192.168.1.71,192.168.1.72     (skip discovery)
#   ... -ServerUrl http://192.168.1.50         (override server base)

param(
    [Parameter(Mandatory = $true)][string]$Password,
    [string[]]$Devices = @(),
    [string]$ServerUrl = ""
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

# ----- server base: this PC + the pinned port (80 -> no port suffix) --
if (-not $ServerUrl) {
    $ip = (Get-NetIPAddress -AddressFamily IPv4 |
           Where-Object { $_.IPAddress -notlike "169.254*" -and $_.IPAddress -ne "127.0.0.1" } |
           Select-Object -First 1).IPAddress
    $port = 80
    if (Test-Path ".env") {
        $m = [regex]::Match((Get-Content ".env" -Raw), "(?m)^ICTECH_PORT=(\d+)")
        if ($m.Success) { $port = [int]$m.Groups[1].Value }
    }
    if ($port -eq 80) { $ServerUrl = "http://$ip" } else { $ServerUrl = "http://${ip}:$port" }
}
Write-Host "Channel will point at: $ServerUrl"

# ----- package with the server URL baked in ---------------------------
$stage = Join-Path $env:TEMP "ictech-roku-stage"
$zip = Join-Path $env:TEMP "ictech-roku.zip"
Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $zip -Force -ErrorAction SilentlyContinue
Copy-Item "roku" $stage -Recurse
$cfg = Join-Path $stage "source\config.brs"
(Get-Content $cfg -Raw).Replace("__SERVER_BASE__", $ServerUrl) | Set-Content $cfg -Encoding ASCII
Compress-Archive -Path "$stage\*" -DestinationPath $zip
Write-Host "Packaged $zip"

# ----- find Rokus (SSDP) if none named ---------------------------------
if ($Devices.Count -eq 0) {
    Write-Host "Discovering Rokus (SSDP)..."
    $udp = New-Object System.Net.Sockets.UdpClient
    $udp.Client.ReceiveTimeout = 3000
    $msg = [Text.Encoding]::ASCII.GetBytes(
        "M-SEARCH * HTTP/1.1`r`nHOST: 239.255.255.250:1900`r`nMAN: `"ssdp:discover`"`r`nST: roku:ecp`r`nMX: 2`r`n`r`n")
    $endpoint = New-Object System.Net.IPEndPoint ([Net.IPAddress]::Parse("239.255.255.250"), 1900)
    [void]$udp.Send($msg, $msg.Length, $endpoint)
    $found = @{}
    try {
        while ($true) {
            $remote = New-Object System.Net.IPEndPoint ([Net.IPAddress]::Any, 0)
            $bytes = $udp.Receive([ref]$remote)
            $text = [Text.Encoding]::ASCII.GetString($bytes)
            if ($text -match "roku") { $found[$remote.Address.ToString()] = $true }
        }
    } catch {}   # timeout ends the collection window
    $udp.Close()
    $Devices = @($found.Keys)
    if ($Devices.Count -eq 0) {
        Write-Host "No Rokus found. Pass -Devices <ip,...> (and check they're on this VLAN)." -ForegroundColor Red
        exit 1
    }
    Write-Host "Found: $($Devices -join ', ')"
}

# ----- sideload to each -------------------------------------------------
foreach ($d in $Devices) {
    Write-Host "Deploying to $d ..."
    & curl.exe -s --digest -u "rokudev:$Password" `
        -F "mysubmit=Replace" -F "archive=@$zip" "http://$d/plugin_install" | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  OK — icTech channel installed/updated on $d" -ForegroundColor Green
    } else {
        Write-Host "  FAILED on $d (dev mode enabled? password right?)" -ForegroundColor Red
    }
}
Write-Host ""
Write-Host "Done. On each TV: open the icTech channel, pick which display it is (press * later to change)."
