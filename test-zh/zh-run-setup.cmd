@echo off
rem ZiraHive test helper: runs setup.ps1 with fixed answers, transcript into test-zh\zh-setup.log
title ZiraHive test - running setup
cd /d "%~dp0.."
del test-zh\zh-setup.done 2>nul
echo [%time:~0,8%] Running setup.ps1 (media G:\Media, AI off, firewall yes) ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Transcript -Path test-zh\zh-setup.log | Out-Null; & .\setup.ps1 -MediaFolder 'G:\Media' -AI no -Firewall yes; 'exit=' + $LASTEXITCODE; Stop-Transcript | Out-Null"
echo [%time:~0,8%] Setup finished > test-zh\zh-setup.done
echo [%time:~0,8%] Setup finished. This window closes in 30 seconds.
timeout /t 30 >nul
