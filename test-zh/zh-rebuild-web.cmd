@echo off
rem ZiraHive: rebuild and restart only the web app (picks up interface changes). Log goes to test-zh\zh-rebuild-web.log
title ZiraHive - rebuilding the web app
cd /d "%~dp0.."
echo Rebuilding the ZiraHive web app, this takes a few minutes...
docker compose up -d --build web > test-zh\zh-rebuild-web.log 2>&1
if errorlevel 1 (echo Build FAILED - see test-zh\zh-rebuild-web.log) else (echo Done. Refresh ZiraHive in your browser.)
timeout /t 20 >nul
