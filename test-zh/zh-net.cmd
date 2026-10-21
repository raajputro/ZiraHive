@echo off
rem ZiraHive test helper: how Windows reaches port 8080, into test-zh\zh-net.log (changes nothing)
title ZiraHive test - network check
cd /d "%~dp0.."
set LOG=test-zh\zh-net.log
echo [%time:~0,8%] Started > %LOG%

echo [%time:~0,8%] 1/6 IPv4 127.0.0.1:8080 ...
echo === [%time:~0,8%] curl 127.0.0.1 >> %LOG%
curl.exe -s -m 8 -o NUL -w "code=%%{http_code} time=%%{time_total}" http://127.0.0.1:8080/api/health >> %LOG% 2>&1
echo. >> %LOG%

echo [%time:~0,8%] 2/6 IPv6 [::1]:8080 ...
echo === [%time:~0,8%] curl ::1 >> %LOG%
curl.exe -s -m 8 -o NUL -w "code=%%{http_code} time=%%{time_total}" http://[::1]:8080/api/health >> %LOG% 2>&1
echo. >> %LOG%

echo [%time:~0,8%] 3/6 localhost:8080 ...
echo === [%time:~0,8%] curl localhost verbose >> %LOG%
curl.exe -s -v -m 8 -o NUL http://localhost:8080/api/health >> %LOG% 2>&1

echo [%time:~0,8%] 4/6 LAN address 192.168.50.94:8080 ...
echo === [%time:~0,8%] curl LAN >> %LOG%
curl.exe -s -m 8 -o NUL -w "code=%%{http_code} time=%%{time_total}" http://192.168.50.94:8080/api/health >> %LOG% 2>&1
echo. >> %LOG%

echo [%time:~0,8%] 5/6 Listening sockets ...
echo === [%time:~0,8%] listening >> %LOG%
netstat -ano -p TCP | findstr LISTENING | findstr ":8080 :8081 :80 " >> %LOG% 2>&1
netstat -ano -p TCPv6 | findstr LISTENING | findstr ":8080" >> %LOG% 2>&1
docker port zirahive-web-1 >> %LOG% 2>&1

echo [%time:~0,8%] 6/6 Same check the setup script does (PowerShell) ...
echo === [%time:~0,8%] powershell localhost >> %LOG%
powershell -NoProfile -Command "$s=Get-Date; try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 8 http://localhost:8080/api/health).StatusCode } catch { $_.Exception.Message }; 'took ' + [int]((Get-Date)-$s).TotalSeconds + 's'" >> %LOG% 2>&1
echo === [%time:~0,8%] powershell 127.0.0.1 >> %LOG%
powershell -NoProfile -Command "$s=Get-Date; try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 8 http://127.0.0.1:8080/api/health).StatusCode } catch { $_.Exception.Message }; 'took ' + [int]((Get-Date)-$s).TotalSeconds + 's'" >> %LOG% 2>&1

echo === [%time:~0,8%] end >> %LOG%
echo.
echo [%time:~0,8%] All done. This window closes in 15 seconds.
timeout /t 15 >nul
