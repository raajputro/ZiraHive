# ZiraHive first-time setup for Windows.
#   Right-click > Run with PowerShell   (or:  powershell -ExecutionPolicy Bypass -File setup.ps1)
#
# Creates .env from .env.example with a random database password, asks where your media folder
# is (ZiraHive reads only that folder), and starts ZiraHive with Docker.
#   .\setup.ps1 -MediaFolder G:\Media    answers the question up front

param([string]$MediaFolder)

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
if (-not $MediaFolder) {
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
$volumes = @()
try { $volumes = @(docker volume ls -q 2>$null) } catch { }
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
$old = @()
try { $old = @(docker ps -aq --filter "label=com.docker.compose.project=gharbox" 2>$null) } catch { }
if ($old.Count -gt 0) {
    Write-Host "Stopping the old GharBox containers (your data stays)..."
    docker rm -f $old | Out-Null
}

$port = if ($envText -match "(?m)^ZIRAHIVE_HTTP_PORT=(\d+)") { $Matches[1] } else { "8080" }

# This PC's address on the home network, for Chromecasts and smart TVs.
$lan = $null
try {
    $lan = (Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" } |
        Select-Object -First 1).IPv4Address.IPAddress
} catch { }
if ($lan -and $envText -notmatch "(?m)^ZIRAHIVE_LAN_URL=\S") {
    $envText = Set-EnvLine $envText "ZIRAHIVE_LAN_URL" "http://${lan}:$port"
}

Set-Content -Path .env -Value $envText -Encoding UTF8 -NoNewline

Write-Host "Starting ZiraHive. The first time takes 10-20 minutes while Docker builds it..."
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { Write-Host "Docker couldn't start ZiraHive. Is Docker Desktop running?" -ForegroundColor Yellow; exit 1 }

Write-Host ""
Write-Host "ZiraHive is running: http://localhost:$port" -ForegroundColor Green
if ($lan) { Write-Host "On phones and TVs at home: http://${lan}:$port" }
Write-Host "Create your admin account there. Your categories appear in Watch, Listen and Read as soon as"
Write-Host "the first scan finishes. To use another media folder later, run this again."
Start-Process "http://localhost:$port"
