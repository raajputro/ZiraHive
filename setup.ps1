# GharBox first-time setup for Windows.
#   Right-click > Run with PowerShell   (or:  powershell -ExecutionPolicy Bypass -File setup.ps1)
#
# Creates .env from .env.example with a random database password, finds your drives so you can
# pick media folders where they already are, and starts GharBox with Docker.

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Set-EnvLine([string]$text, [string]$key, [string]$value) {
    $pattern = "(?m)^#?[ \t]*$key=[^\r\n]*"
    if ($text -match $pattern) { return [regex]::Replace($text, $pattern, "$key=$value") }
    return $text.TrimEnd() + "`r`n$key=$value`r`n"
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Docker Desktop isn't installed. Get it free from https://www.docker.com/products/docker-desktop/ , start it, then run this again." -ForegroundColor Yellow
    exit 1
}

if (Test-Path .env) {
    $envText = Get-Content .env -Raw
    Write-Host "Found .env, keeping your settings."
} else {
    $envText = Get-Content .env.example -Raw
    $bytes = New-Object byte[] 24
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $password = -join ($bytes | ForEach-Object { $_.ToString("x2") })
    $envText = Set-EnvLine $envText "POSTGRES_PASSWORD" $password
    Write-Host "Created .env with a random database password."
}

# Where GharBox keeps photos, files and its database: the drive with the most free space.
$dataOk = $false
if ($envText -match "(?m)^GHARBOX_DATA_PATH=([A-Za-z]):") { $dataOk = Test-Path "$($Matches[1]):\" }
if (-not $dataOk) {
    $biggest = Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Free -gt 0 -and $_.Name.Length -eq 1 } |
        Sort-Object Free -Descending | Select-Object -First 1
    $envText = Set-EnvLine $envText "GHARBOX_DATA_PATH" "$($biggest.Name):/GharBoxData"
}

# Every drive with a letter from C to J becomes pickable (read-only) in Settings.
$found = @()
foreach ($d in Get-PSDrive -PSProvider FileSystem) {
    if ($d.Name -match "^[C-Jc-j]$" -and (Test-Path "$($d.Name):\")) {
        $letter = $d.Name.ToUpper()
        $envText = Set-EnvLine $envText "DRIVE_$letter" "${letter}:/"
        $found += "${letter}:"
    }
}
$port = if ($envText -match "(?m)^GHARBOX_HTTP_PORT=(\d+)") { $Matches[1] } else { "8080" }

# This PC's address on the home network, for Chromecasts and smart TVs.
$lan = $null
try {
    $lan = (Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" } |
        Select-Object -First 1).IPv4Address.IPAddress
} catch { }
if ($lan -and $envText -notmatch "(?m)^GHARBOX_LAN_URL=\S") {
    $envText = Set-EnvLine $envText "GHARBOX_LAN_URL" "http://${lan}:$port"
}

Set-Content -Path .env -Value $envText -Encoding UTF8 -NoNewline
Write-Host ("Drives GharBox can read (read-only): " + ($found -join ", "))

Write-Host "Starting GharBox. The first time takes 10-20 minutes while Docker builds it..."
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { Write-Host "Docker couldn't start GharBox. Is Docker Desktop running?" -ForegroundColor Yellow; exit 1 }

Write-Host ""
Write-Host "GharBox is running: http://localhost:$port" -ForegroundColor Green
if ($lan) { Write-Host "On phones and TVs at home: http://${lan}:$port" }
Write-Host "Create your admin account there, then Settings > Server > Categories > Choose folder"
Write-Host "to add your movie, music and book folders where they already are."
Start-Process "http://localhost:$port"
