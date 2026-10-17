# Update ZiraHive: get the newest code (when this folder came from git), rebuild and restart.
# Your settings, files and database stay; the database is upgraded by itself when ZiraHive starts.
#   Right-click > Run with PowerShell
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
if ((Test-Path .git) -and (Get-Command git -ErrorAction SilentlyContinue)) {
    $remote = (& git remote) -join ""
    if ($remote) {
        Write-Host "Getting the newest version..."
        git pull --ff-only
        if ($LASTEXITCODE -ne 0) { Write-Host "Couldn't update the code (changed files here?). Nothing was restarted." -ForegroundColor Yellow; exit 1 }
    }
}
& (Join-Path $PSScriptRoot "setup.ps1") -Update
