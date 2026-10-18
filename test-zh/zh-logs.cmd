@echo off
rem ZiraHive test helper: container status and recent logs into test-zh\zh-logs.log (changes nothing)
title ZiraHive test - collecting logs
cd /d "%~dp0.."
set LOG=test-zh\zh-logs.log
echo [%time:~0,8%] Started > %LOG%
call :step "Container status"        "docker compose ps -a"
call :step "API logs"                "docker compose logs --tail 120 api"
call :step "Worker logs"             "docker compose logs --tail 40 worker"
call :step "Web logs"                "docker compose logs --tail 40 web"
call :step "Database logs"           "docker compose logs --tail 30 postgres"
call :step "Health from inside"      "docker compose exec -T api python -c ""import urllib.request;print(urllib.request.urlopen('http://localhost:8000/api/health',timeout=5).read())"""
call :step "Health on port 8080"     "curl.exe -s -m 10 -o NUL -w ""%%{http_code} %%{time_total}s"" http://localhost:8080/api/health"
call :step "Who uses port 8080"      "netstat -ano | findstr :8080"
echo [%time:~0,8%] All done >> %LOG%
echo.
echo [%time:~0,8%] All done. This window closes in 15 seconds.
timeout /t 15 >nul
exit /b

:step
echo [%time:~0,8%] %~1 ...
echo. >> %LOG%
echo === [%time:~0,8%] %~1 >> %LOG%
cmd /c %~2 >> %LOG% 2>&1
exit /b
