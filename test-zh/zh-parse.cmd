@echo off
rem ZiraHive test helper: syntax check of setup.ps1 and update.ps1 with this PC's PowerShell (runs nothing)
title ZiraHive test - syntax check
cd /d "%~dp0.."
echo [%time:~0,8%] 1/1 Checking setup.ps1 and update.ps1 ...
powershell -NoProfile -Command "foreach ($f in 'setup.ps1','update.ps1') { $t=$null; $e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path $f), [ref]$t, [ref]$e); if ($e) { $e | ForEach-Object { \"$f line $($_.Extent.StartLineNumber): $($_.Message)\" } } else { \"$f OK\" } }; $PSVersionTable.PSVersion.ToString(); (Get-Command New-NetFirewallHyperVRule -ErrorAction SilentlyContinue) -ne $null" > test-zh\zh-parse.log 2>&1
echo [%time:~0,8%] All done. This window closes in 10 seconds.
timeout /t 10 >nul
