# Move ZiraHive's data folder (backed-up photos and files, the vault, thumbnails, plugins, AI models)
# to another drive or folder.
#   Right-click > Run with PowerShell   (or:  powershell -ExecutionPolicy Bypass -File move-data.ps1)
#   .\move-data.ps1 -To E:\ZiraHiveData        no question about where
#   .\move-data.ps1 -To E: -Yes                 E:\<same folder name>, without asking to go ahead
#
# ZiraHive is stopped, everything is copied, the copy is checked file by file, ZIRAHIVE_DATA_PATH in
# .env is pointed at it, and ZiraHive is started again. Nothing inside changes: ZiraHive always sees
# the folder as /data, so no paths need fixing. The old folder is kept until you say it can go; if
# anything goes wrong, ZiraHive is started again on the old folder as before.
# (The database - accounts, watch history, albums - is not in this folder; Docker keeps it.)

param([string]$To, [switch]$Yes)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Invoke-Quiet([scriptblock]$block) {
    $saved = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try { & $block 2>$null | Out-Null; return ($LASTEXITCODE -eq 0) } catch { return $false }
    finally { $ErrorActionPreference = $saved }
}
function Set-EnvLine([string]$text, [string]$key, [string]$value) {
    $pattern = "(?m)^#?[ \t]*$key=[^\r\n]*"
    if ($text -match $pattern) { return [regex]::Replace($text, $pattern, "$key=$value") }
    return $text.TrimEnd() + "`r`n$key=$value`r`n"
}
function Get-FolderTotals([string]$path) {
    $m = Get-ChildItem -LiteralPath $path -Recurse -Force -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum
    return [pscustomobject]@{ Files = [int64]$m.Count; Bytes = [int64]$(if ($m.Sum) { $m.Sum } else { 0 }) }
}
function Format-Size([int64]$bytes) {
    if ($bytes -ge 1GB) { return "{0:N1} GB" -f ($bytes / 1GB) }
    return "{0:N0} MB" -f ($bytes / 1MB)
}
function Test-Inside([string]$child, [string]$parent) {
    $c = $child.TrimEnd("\") + "\"; $p = $parent.TrimEnd("\") + "\"
    return $c.StartsWith($p, [StringComparison]::OrdinalIgnoreCase)
}
function Wait-Answer([string]$port) {
    # 127.0.0.1, not localhost: see setup.ps1 (Windows tries IPv6 first, which Docker may not answer)
    $started = Get-Date
    while (((Get-Date) - $started).TotalMinutes -lt 5) {
        try { if ((Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 "http://127.0.0.1:$port/api/health").StatusCode -eq 200) { return $true } } catch { }
        Start-Sleep -Seconds 2
    }
    return $false
}

# ------------------------------------------------------------------ where it is now
$envFile = Join-Path $PSScriptRoot ".env"
if (-not (Test-Path $envFile)) { Write-Host "There's no .env here yet: run setup.ps1 first." -ForegroundColor Yellow; exit 1 }
$envText = [IO.File]::ReadAllText($envFile)
$key = "ZIRAHIVE_DATA_PATH"
if ($envText -notmatch "(?m)^ZIRAHIVE_DATA_PATH=" -and $envText -match "(?m)^GHARBOX_DATA_PATH=") { $key = "GHARBOX_DATA_PATH" }
$current = if ($envText -match "(?m)^$key=([^\r\n]*\S)") { $Matches[1] } else { "./zirahive-data" }
$source = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot $current.Replace("/", "\")))
if (-not (Test-Path -LiteralPath $source -PathType Container)) {
    Write-Host "The data folder in .env ($source) doesn't exist, so there's nothing to move." -ForegroundColor Yellow
    exit 1
}
$port = if ($envText -match "(?m)^ZIRAHIVE_HTTP_PORT=(\d+)") { $Matches[1] } else { "8080" }

Write-Host "ZiraHive's data folder is $source"
Write-Host "Measuring it..."
$before = Get-FolderTotals $source
Write-Host ("  {0:N0} files, {1}" -f $before.Files, (Format-Size $before.Bytes))

# ------------------------------------------------------------------ where it should go
if (-not $To) {
    Write-Host ""
    Write-Host "Drives on this PC:"
    Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | ForEach-Object {
        Write-Host ("  {0}  {1,10} free of {2}" -f $_.DeviceID, (Format-Size $_.FreeSpace), (Format-Size $_.Size))
    }
    Write-Host ""
    $To = Read-Host "Move it to which drive or folder? (for example  E:  or  E:\ZiraHiveData)"
}
$To = $To.Trim().Trim('"')
if (-not $To) { Write-Host "Nothing chosen; nothing changed."; exit 0 }
if ($To -match '^[A-Za-z]:\\?$') { $To = $To.Substring(0, 2) + "\" + (Split-Path $source -Leaf) }  # a drive: same folder name there
if (-not [IO.Path]::IsPathRooted($To)) { Write-Host "Please give a full path such as E:\ZiraHiveData." -ForegroundColor Yellow; exit 1 }
$dest = [IO.Path]::GetFullPath($To).TrimEnd("\")

if ($dest -eq $source.TrimEnd("\")) { Write-Host "That's where it already is; nothing changed."; exit 0 }
if ((Test-Inside $dest $source) -or (Test-Inside $source $dest)) {
    Write-Host "The new folder can't be inside the old one (or the other way round). Pick another place." -ForegroundColor Yellow
    exit 1
}
if ($dest -match '^\\\\') { Write-Host "Network folders don't work for this (Docker can't keep files there reliably). Pick a drive on this PC." -ForegroundColor Yellow; exit 1 }
$letter = $dest.Substring(0, 2).ToUpper()
$disk = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$letter'"
if (-not $disk) { Write-Host "There's no drive $letter on this PC." -ForegroundColor Yellow; exit 1 }
if ($disk.DriveType -eq 4) { Write-Host "$letter is a network drive, which doesn't work for this. Pick a drive inside this PC." -ForegroundColor Yellow; exit 1 }
if ($disk.DriveType -eq 2) {
    Write-Host "$letter is a removable drive. ZiraHive stops working whenever it's unplugged." -ForegroundColor Yellow
    if (-not $Yes -and (Read-Host "Use it anyway? (y/N)") -notmatch '^[yY]') { Write-Host "Nothing changed."; exit 0 }
}
if (Test-Path -LiteralPath $dest) {
    if (Get-ChildItem -LiteralPath $dest -Force | Select-Object -First 1) {
        Write-Host "$dest already has files in it. Pick an empty or new folder, so nothing gets mixed up." -ForegroundColor Yellow
        exit 1
    }
}
$needed = [int64]($before.Bytes * 1.05) + 1GB
if ($disk.FreeSpace -lt $needed) {
    Write-Host ("Not enough room on {0}: {1} free, about {2} needed." -f $letter, (Format-Size $disk.FreeSpace), (Format-Size $needed)) -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "This will:"
Write-Host "  1. stop ZiraHive (it's unavailable while copying)"
Write-Host "  2. copy $source  ->  $dest"
Write-Host "  3. check every file arrived, point .env at the new folder and start ZiraHive"
Write-Host "  The old folder stays until you choose to delete it at the end."
if (-not $Yes -and (Read-Host "Go ahead? (y/N)") -notmatch '^[yY]') { Write-Host "Nothing changed."; exit 0 }

# ------------------------------------------------------------------ stop, copy, check
if (-not (Invoke-Quiet { docker info })) { Write-Host "Docker isn't running. Start Docker Desktop and run this again." -ForegroundColor Yellow; exit 1 }
Write-Host ""
Write-Host "Stopping ZiraHive..."
docker compose stop
if ($LASTEXITCODE -ne 0) { Write-Host "Couldn't stop ZiraHive; nothing was copied." -ForegroundColor Yellow; exit 1 }

function Restore-Old([string]$why) {
    Write-Host $why -ForegroundColor Yellow
    [IO.File]::WriteAllText($envFile, $envText, (New-Object Text.UTF8Encoding $false))
    Write-Host "Starting ZiraHive again on the old folder ($source)..."
    docker compose up -d | Out-Null
    if (Wait-Answer $port) { Write-Host "ZiraHive is running as before. The partial copy in $dest can be deleted." }
    else { Write-Host "ZiraHive didn't answer; 'docker compose logs api' says why." -ForegroundColor Yellow }
    exit 1
}

$log = Join-Path $PSScriptRoot "move-data.log"
Write-Host "Copying (the log is in move-data.log)..."
# /E everything, /COPY:DAT /DCOPY:DAT keep dates, /XJ skip junctions, /MT:16 copy 16 files at a time
robocopy $source $dest /E /COPY:DAT /DCOPY:DAT /XJ /R:2 /W:2 /MT:16 /NP /NFL /NDL /LOG:"$log" | Out-Null
if ($LASTEXITCODE -ge 8) { Restore-Old "The copy failed (robocopy code $LASTEXITCODE, see move-data.log)." }

Write-Host "Checking the copy..."
$after = Get-FolderTotals $dest
if ($after.Files -ne $before.Files -or $after.Bytes -ne $before.Bytes) {
    Restore-Old ("The copy doesn't match: {0:N0} files / {1} copied, {2:N0} files / {3} expected." -f $after.Files, (Format-Size $after.Bytes), $before.Files, (Format-Size $before.Bytes))
}
Write-Host ("  all {0:N0} files, {1}" -f $after.Files, (Format-Size $after.Bytes))

# ------------------------------------------------------------------ switch over
Copy-Item -LiteralPath $envFile -Destination (Join-Path $PSScriptRoot ".env.before-move") -Force
$newText = Set-EnvLine $envText $key ($dest.Replace("\", "/"))
[IO.File]::WriteAllText($envFile, $newText, (New-Object Text.UTF8Encoding $false))
Write-Host "Starting ZiraHive on the new folder..."
docker compose up -d
if ($LASTEXITCODE -ne 0 -or -not (Wait-Answer $port)) { Restore-Old "ZiraHive didn't start on the new folder." }

Write-Host ""
Write-Host "Done: ZiraHive now keeps its data in $dest" -ForegroundColor Green
Write-Host "Open it and look at a few photos to be sure. Your old .env is saved as .env.before-move."
Write-Host ""
if (-not $Yes -and (Read-Host "Delete the old folder $source now to free $(Format-Size $before.Bytes)? (y/N)") -match '^[yY]') {
    Write-Host "Deleting the old folder..."
    Remove-Item -LiteralPath $source -Recurse -Force
    Write-Host "Deleted."
} else {
    Write-Host "The old folder is still at $source. Delete it yourself once you're happy."
}
