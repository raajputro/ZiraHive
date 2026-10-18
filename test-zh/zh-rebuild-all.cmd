@echo off
rem ZiraHive: rebuild and restart everything (server + web app) after the Live TV update. Log goes to test-zh\zh-rebuild-all.log
title ZiraHive - rebuilding
cd /d "%~dp0.."
echo Rebuilding ZiraHive (server and web app), this takes a few minutes...
docker compose up -d --build > test-zh\zh-rebuild-all.log 2>&1
if errorlevel 1 (echo Build FAILED - see test-zh\zh-rebuild-all.log) else (echo Done. Refresh ZiraHive and open Live TV.)
timeout /t 20 >nul
