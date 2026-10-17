# ZiraHive first-time setup for Windows.
#   Right-click > Run with PowerShell   (or:  powershell -ExecutionPolicy Bypass -File setup.ps1)
#
# Creates .env from .env.example with a random database password, asks where your media folder
# is (ZiraHive reads only that folder) and whether to turn on the local AI, then starts ZiraHive
# with Docker and opens it once it answers.
#   .\setup.ps1 -MediaFolder G:\Media -AI no -Firewall yes    answers the questions up front
#   .\setup.ps1 -Update                         no questions: keep the settings, rebuild, restart

param([string]$MediaFolder, [ValidateSet("", "yes", "no")][string]$AI = "",
      [ValidateSet("", "yes", "no")][string]$Firewall = "", [switch]$Update)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

# Windows PowerShell 5.1 turns a program's error output into errors when it is redirected, and
# "Stop" would end the script over a harmless warning; so ask Docker quietly, like this.
function Invoke-Quiet([scriptblock]$block) {
    $saved = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try { & $block 2>$null | Out-Null; return ($LASTEXITCODE -eq 0) } catch { return $false }
    finally { $ErrorActionPreference = $saved }
}
function Get-Quiet([scriptblock]$block) {
    $saved = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try { return @(& $block 2>$null) } catch { return @() } finally { $ErrorActionPreference = $saved }
}

function Set-EnvLine([string]$text, [string]$key, [string]$value) {
    $pattern = "(?m)^#?[ \t]*$key=[^\r\n]*"
    if ($text -match $pattern) { return [regex]::Replace($text, $pattern, "$key=$value") }
    return $text.TrimEnd() + "`r`n$key=$value`r`n"
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Docker Desktop isn't installed. Get it free from https://www.docker.com/products/docker-desktop/ , start it, then run this again." -ForegroundColor Yellow
    exit 1
}
if (-not (Invoke-Quiet { docker info })) {
    $desktop = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    if (Test-Path $desktop) {
        Write-Host "Starting Docker Desktop (this can take a minute)..."
        Start-Process $desktop
        for ($i = 0; $i -lt 60 -and -not (Invoke-Quiet { docker info }); $i++) { Start-Sleep -Seconds 3 }
    }
    if (-not (Invoke-Quiet { docker info })) {
        Write-Host "Docker Desktop isn't running. Start it, wait until it says it's running, then run this again." -ForegroundColor Yellow
        Write-Host "If it complains about WSL, run 'wsl --update' in PowerShell as administrator and restart the PC."
        exit 1
    }
}

if (Test-Path .env) {
    $envText = Get-Content .env -Raw
    Write-Host "Found .env, keeping your settings."
    # ZiraHive used to be called GharBox: settings keep working under the new names.
    if ($envText -match "(?m)^#?[ \t]*GHARBOX_") {
        $envText = [regex]::Replace($envText, "(?m)^(#?[ \t]*)GHARBOX_", '${1}ZIRAHIVE_')
        Write-Host "Renamed the GHARBOX_ settings in .env to ZIRAHIVE_."
    }
} else {
    $envText = Get-Content .env.example -Raw
    $bytes = New-Object byte[] 24
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $password = -join ($bytes | ForEach-Object { $_.ToString("x2") })
    $envText = Set-EnvLine $envText "POSTGRES_PASSWORD" $password
    Write-Host "Created .env with a random database password."
}

# Where ZiraHive keeps photos, files and its database: the drive with the most free space.
$dataOk = $false
if ($envText -match "(?m)^ZIRAHIVE_DATA_PATH=([A-Za-z]):") { $dataOk = Test-Path "$($Matches[1]):\" }
if (-not $dataOk) {
    $biggest = Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Free -gt 0 -and $_.Name.Length -eq 1 } |
        Sort-Object Free -Descending | Select-Object -First 1
    $envText = Set-EnvLine $envText "ZIRAHIVE_DATA_PATH" "$($biggest.Name):/ZiraHiveData"
}

# The media folder: ZiraHive reads only this folder (never changes, moves or copies anything),
# and every folder inside it becomes a category: G:\Media\English Movies -> "English Movies".
function Get-Kind([string]$name) {
    if ($name -match "audio ?books?|golpo|story ?tapes?") { return "audiobooks" }
    if ($name -match "music|songs?\b|gaan|sangeet|sangit|geet|qawwali|mp3|albums?\b|playlist") { return "music" }
    if ($name -match "comic|manga|manhwa|webtoon|graphic novel") { return "comics" }
    if ($name -match "books?\b|ebook|novel|pdfs?\b|reading|library|\bboi\b") { return "books" }
    if ($name -match "series|\bshows?\b|\btv\b|drama|sitcom|season|natok|serial") { return "series" }
    if ($name -match "anim|cartoon|kids|children|anime") { return "movies + series" }
    return "movies"
}

$current = if ($envText -match "(?m)^MEDIA_PATH=([^\r\n]*\S)") { $Matches[1] } else { "" }
if ($Update -and -not $MediaFolder) { $MediaFolder = $current }
if (-not $MediaFolder -and -not $Update) {
    Write-Host ""
    Write-Host "Where are your movies, series, music and books? Type the folder, for example G:\Media" -ForegroundColor Cyan
    Write-Host "ZiraHive only reads it: nothing is moved, copied or changed. Other folders and drives stay hidden."
    while ($true) {
        $prompt = if ($current) { "Media folder (Enter keeps $current)" } else { "Media folder (Enter to skip for now)" }
        $answer = (Read-Host $prompt).Trim().Trim('"')
        if ($answer -match '^[A-Za-z]:$') { $answer += "\" }  # a whole drive
        if (-not $answer) { $MediaFolder = $current; break }
        if (Test-Path -LiteralPath $answer -PathType Container) { $MediaFolder = $answer; break }
        Write-Host "  There's no folder $answer. Check the drive letter and the name." -ForegroundColor Yellow
    }
}
if ($MediaFolder) {
    if ($MediaFolder -match '^[A-Za-z]:$') { $MediaFolder += "\" }
    $full = (Resolve-Path -LiteralPath $MediaFolder).Path.TrimEnd("\")
    if ($full -match '^[A-Za-z]:$') { $full += "\" }  # G:\ stays G:\ (Docker needs the slash)
    $dataPath = if ($envText -match "(?m)^ZIRAHIVE_DATA_PATH=([^\r\n]*\S)") { $Matches[1].Replace("/", "\").TrimEnd("\") } else { "" }
    if ($dataPath -and ($dataPath -ieq $full -or $dataPath.StartsWith($full.TrimEnd("\") + "\", "OrdinalIgnoreCase"))) {
        Write-Host "  That folder holds ZiraHive's own data ($dataPath); it won't show up as media." -ForegroundColor Yellow
    }
    $envText = Set-EnvLine $envText "MEDIA_PATH" ($full.Replace("\", "/"))
    $folders = @(Get-ChildItem -LiteralPath $full -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -notmatch '^[.$]' -and $_.Name -ne "System Volume Information" })
    Write-Host ""
    if ($folders.Count -eq 0) {
        Write-Host "  $full has no folders inside yet. Make one per kind (English Movies, Web Series, Music, ...)."
    } else {
        Write-Host "  These become your categories (rename them or change the type later in Settings):"
        foreach ($f in $folders) {
            $name = (($f.Name -split "[\s_.\-]+" | Where-Object { $_ } |
                ForEach-Object { if ($_ -cmatch "[A-Z]") { $_ } else { $_.Substring(0,1).ToUpper() + $_.Substring(1) } }) -join " ")
            Write-Host ("    {0,-32} {1}" -f $name, (Get-Kind $name))
        }
    }
    Write-Host "  New folders you make there later are added by themselves (every night, or Settings > Find new folders)."
}

# An install from before the rename keeps its database and Tailscale sign-in (Docker volumes),
# and its old containers are stopped so they don't hold the port.
$volumes = Get-Quiet { docker volume ls -q }
# Remote access was in use if a Tailscale container ever ran (before or after the rename)
$usedTailscale = (Get-Quiet { docker ps -aq --filter "label=com.docker.compose.service=tailscale" }).Count -gt 0
function Use-OldVolume([string]$kind, [string]$key) {
    if (($volumes -contains "gharbox_$kind") -and -not ($volumes -contains "zirahive_$kind") -and
        ($script:envText -notmatch "(?m)^$key=\S")) {
        $script:envText = Set-EnvLine $script:envText $key "gharbox_$kind"
        return $true
    }
    return $false
}
if (Use-OldVolume "postgres-data" "DATABASE_VOLUME") {
    # the database inside still has its old user and name
    if ($envText -notmatch "(?m)^POSTGRES_USER=\S") { $envText = Set-EnvLine $envText "POSTGRES_USER" "gharbox" }
    if ($envText -notmatch "(?m)^POSTGRES_DB=\S") { $envText = Set-EnvLine $envText "POSTGRES_DB" "gharbox" }
    Write-Host "Keeping your existing database."
}
if (Use-OldVolume "tailscale-state" "TAILSCALE_VOLUME") {
    Write-Host "Keeping your Tailscale sign-in. Your address becomes https://zirahive.<your-tailnet>.ts.net"
    if ($envText -match "(?m)^ZIRAHIVE_PUBLIC_URL=https://gharbox\.") {
        $envText = [regex]::Replace($envText, "(?m)^(ZIRAHIVE_PUBLIC_URL=https://)gharbox\.", '${1}zirahive.')
    }
}
[void](Use-OldVolume "caddy-data" "CADDY_VOLUME")
[void](Use-OldVolume "ollama-models" "OLLAMA_VOLUME")
$old = Get-Quiet { docker ps -aq --filter "label=com.docker.compose.project=gharbox" }
if ($old.Count -gt 0) {
    Write-Host "Stopping the old GharBox containers (your data stays)..."
    docker rm -f $old | Out-Null
}

$port = if ($envText -match "(?m)^ZIRAHIVE_HTTP_PORT=(\d+)") { $Matches[1] } else { "8080" }

# Local AI (optional): photo search, faces, subtitles, questions. COMPOSE_PROFILES in .env makes
# "docker compose up -d" start those containers too.
# (a list, always: PowerShell turns a one-item list into plain text unless told otherwise)
[string[]]$profiles = @()
if ($envText -match "(?m)^COMPOSE_PROFILES=([^\r\n]*)") {
    $profiles = @($Matches[1].Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ })
}
if (-not $AI -and -not $Update) {
    $gb = 0
    try { $gb = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB) } catch { }
    Write-Host ""
    Write-Host "Turn on the local AI? Search photos by what's in them, group faces, make subtitles and ask" -ForegroundColor Cyan
    Write-Host "questions about your documents, all on this PC. It downloads about 3-4 GB once and needs"
    Write-Host "8 GB of memory or more$(if ($gb) { " (this PC has $gb GB)" }). You can change your mind later by running this again."
    $now = $profiles -contains "ai"
    $reply = (Read-Host "Local AI? (y/n, Enter keeps it $(if ($now) { 'on' } else { 'off' }))").Trim().ToLower()
    $AI = if ($reply.StartsWith("y")) { "yes" } elseif ($reply.StartsWith("n")) { "no" } elseif ($now) { "yes" } else { "no" }
}
if ($AI -eq "yes" -and $profiles -notcontains "ai") { $profiles += "ai" }
if ($AI -eq "no") { $profiles = @($profiles | Where-Object { $_ -ne "ai" }) }
if (-not $profiles) { $profiles = @() }
# remote access starts by itself once Tailscale has been set up (docs/REMOTE_ACCESS.md)
if (($envText -match "(?m)^TS_AUTHKEY=\S") -or $usedTailscale) {
    if ($profiles -notcontains "remote") { $profiles += "remote" }
}
$envText = Set-EnvLine $envText "COMPOSE_PROFILES" ($profiles -join ",")

# Is something else already using the port?
try {
    $busy = Get-NetTCPConnection -LocalPort ([int]$port) -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($busy) {
        $who = (Get-Process -Id $busy.OwningProcess -ErrorAction SilentlyContinue).ProcessName
        if ($who -and $who -notmatch "docker|wslrelay|vpnkit|com\.docker") {
            Write-Host "Port $port is already used by '$who'. Close it, or set ZIRAHIVE_HTTP_PORT=8090 in .env and run this again." -ForegroundColor Yellow
            exit 1
        }
    }
} catch { }

# Room for backups?
if ($envText -match "(?m)^ZIRAHIVE_DATA_PATH=([A-Za-z]):") {
    $drive = Get-PSDrive -Name $Matches[1] -ErrorAction SilentlyContinue
    if ($drive -and $drive.Free -lt 20GB) {
        Write-Host ("Only {0:N0} GB free on {1}: for photo backups, a drive with more room is better (ZIRAHIVE_DATA_PATH in .env)." -f ($drive.Free / 1GB), "$($drive.Name):") -ForegroundColor Yellow
    }
}

# This PC's address on the home network, for Chromecasts and smart TVs.
$lan = $null
try {
    $lan = (Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" } |
        Select-Object -First 1).IPv4Address.IPAddress
} catch { }
if ($lan -and $envText -notmatch "(?m)^ZIRAHIVE_LAN_URL=\S") {
    $envText = Set-EnvLine $envText "ZIRAHIVE_LAN_URL" "http://${lan}:$port"
}

# UTF-8 without the byte-order mark Windows PowerShell adds, which Docker Compose may misread
[IO.File]::WriteAllText((Join-Path $PSScriptRoot ".env"), $envText, (New-Object Text.UTF8Encoding $false))

Write-Host ""
Write-Host "Starting ZiraHive$(if ($profiles) { " (with: $($profiles -join ', '))" }). The first time takes 10-20 minutes while Docker builds it..."
docker compose up -d --build --remove-orphans
if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker couldn't start ZiraHive. The lines above say why; 'docker compose logs' shows more." -ForegroundColor Yellow
    exit 1
}

# 127.0.0.1, not localhost: Windows tries IPv6 (::1) first for localhost, which Docker doesn't always
# answer (WSL "mirrored" networking), and PowerShell 5.1 then waits instead of trying IPv4.
$started = Get-Date
$up = $false
while (-not $up -and ((Get-Date) - $started).TotalMinutes -lt 20) {
    $secs = [int]((Get-Date) - $started).TotalSeconds
    Write-Host -NoNewline ("`rWaiting for ZiraHive to answer... {0}:{1:00}  " -f [int][math]::Floor($secs / 60), ($secs % 60))
    try { $up = (Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 "http://127.0.0.1:$port/api/health").StatusCode -eq 200 } catch { }
    if (-not $up) { Start-Sleep -Seconds 2 }
}
Write-Host ""
if (-not $up) {
    Write-Host "ZiraHive started but isn't answering yet. What it says:" -ForegroundColor Yellow
    docker compose logs --tail 30 api
    Write-Host "Check everything with:  docker compose exec api python -m app.doctor"
    exit 1
}

# Phones and TVs at home need the port open in Windows Firewall. With WSL's "mirrored" networking,
# Docker's ports also pass WSL's own (Hyper-V) firewall, which blocks other devices by default.
$wslMirrored = $false
try {
    $wslcfg = Join-Path $env:USERPROFILE ".wslconfig"
    if (Test-Path $wslcfg) { $wslMirrored = [bool](Select-String -Path $wslcfg -Pattern '^\s*networkingMode\s*=\s*mirrored' -Quiet) }
} catch { }
$wslVm = "{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}"  # WSL's id in the Hyper-V firewall
$need = @()
if (-not (Get-NetFirewallRule -DisplayName "ZiraHive" -ErrorAction SilentlyContinue)) {
    $need += "New-NetFirewallRule -DisplayName 'ZiraHive' -Direction Inbound -Protocol TCP -LocalPort $port -Action Allow -Profile Private | Out-Null"
}
if ($wslMirrored -and (Get-Command New-NetFirewallHyperVRule -ErrorAction SilentlyContinue) -and
    -not (Get-NetFirewallHyperVRule -Name "ZiraHive" -ErrorAction SilentlyContinue)) {
    $need += "New-NetFirewallHyperVRule -Name 'ZiraHive' -DisplayName 'ZiraHive' -Direction Inbound -VMCreatorId '$wslVm' -Protocol TCP -LocalPorts $port -Action Allow -Profiles Private | Out-Null"
}
if ($need) {
    $admin = $false
    try { $admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) } catch { }
    $script = "`$ErrorActionPreference='Stop'; " + ($need -join "; ")
    $ok = $false
    if ($admin) {
        try { Invoke-Expression $script; $ok = $true } catch { Write-Host $_.Exception.Message -ForegroundColor Yellow }
    } else {
        $reply = $Firewall
        if (-not $reply -and -not $Update) {
            Write-Host ""
            $reply = (Read-Host "Let phones and TVs on your home Wi-Fi open ZiraHive? Windows will ask for permission (y/n)").Trim().ToLower()
        }
        if ($reply -in @("y", "yes")) {
            try {
                $enc = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($script))
                $p = Start-Process powershell -Verb RunAs -Wait -PassThru -WindowStyle Hidden -ArgumentList "-NoProfile", "-EncodedCommand", $enc
                $ok = $p.ExitCode -eq 0
            } catch { }
        }
    }
    if ($ok) { Write-Host "Allowed ZiraHive through Windows Firewall on your home network." }
    else { Write-Host "Phones may not reach it until port $port is allowed: run this again and answer y." -ForegroundColor Yellow }
}
try {
    $public = Get-NetConnectionProfile -ErrorAction Stop | Where-Object { $_.NetworkCategory -eq "Public" -and $_.IPv4Connectivity -eq "Internet" }
    foreach ($n in $public) {
        Write-Host "Your network '$($n.Name)' is set to Public, so Windows blocks phones from reaching ZiraHive." -ForegroundColor Yellow
        Write-Host "  If it's your home Wi-Fi: Settings > Network & internet > $($n.InterfaceAlias) > $($n.Name) > Private network." -ForegroundColor Yellow
    }
} catch { }

# A shortcut on the desktop
try {
    $desk = [Environment]::GetFolderPath("Desktop")
    if ($desk) { Set-Content -Path (Join-Path $desk "ZiraHive.url") -Value "[InternetShortcut]`r`nURL=http://localhost:$port/`r`n" -Encoding ASCII }
} catch { }

Write-Host ""
Write-Host "ZiraHive is running: http://localhost:$port" -ForegroundColor Green
if ($lan) { Write-Host "On phones and TVs at home: http://${lan}:$port" }
if (-not $Update) {
    Write-Host "Create your admin account there. Your categories appear in Watch, Listen and Read as soon as"
    Write-Host "the first scan finishes. To change the media folder or the AI choice, run this again."
}
Write-Host "Settings > Server > Health shows whether everything is working."
Start-Process "http://localhost:$port"
