@echo off
rem ZiraHive test helper: firewall, network profile and Docker networking facts into test-zh\zh-fw.log (changes nothing)
title ZiraHive test - firewall and Docker network
cd /d "%~dp0.."
set LOG=test-zh\zh-fw.log
echo [%time:~0,8%] Started > %LOG%

echo [%time:~0,8%] 1/5 Everything on port 8080 ...
echo === [%time:~0,8%] netstat 8080 any state >> %LOG%
netstat -ano | findstr ":8080" >> %LOG% 2>&1
echo === listening processes owning many ports >> %LOG%
netstat -abno -p TCP 2>NUL | findstr /i "LISTENING docker wsl vpnkit" >> %LOG% 2>&1

echo [%time:~0,8%] 2/5 Network profile (Private or Public) ...
echo === [%time:~0,8%] profile >> %LOG%
powershell -NoProfile -Command "Get-NetConnectionProfile | Format-Table -AutoSize Name,InterfaceAlias,NetworkCategory,IPv4Connectivity | Out-String -Width 200" >> %LOG% 2>&1

echo [%time:~0,8%] 3/5 Firewall rules for ZiraHive, GharBox and Docker ...
echo === [%time:~0,8%] firewall rules >> %LOG%
powershell -NoProfile -Command "Get-NetFirewallRule | Where-Object { $_.DisplayName -match 'ZiraHive|GharBox|Docker|com.docker|8080|wsl' } | Format-Table -AutoSize DisplayName,Enabled,Direction,Action,Profile | Out-String -Width 200" >> %LOG% 2>&1
powershell -NoProfile -Command "Get-NetFirewallProfile | Format-Table -AutoSize Name,Enabled,DefaultInboundAction | Out-String -Width 200" >> %LOG% 2>&1

echo [%time:~0,8%] 4/5 Docker Desktop network settings ...
echo === [%time:~0,8%] docker settings >> %LOG%
powershell -NoProfile -Command "$f=Join-Path $env:APPDATA 'Docker\settings-store.json'; if (Test-Path $f) { Get-Content $f | Select-String -Pattern 'Network|Wsl|Kernel|Proxy|Port|Host|IPv6|Mirror' } else { 'no settings-store.json' }" >> %LOG% 2>&1
echo === wslconfig >> %LOG%
type "%USERPROFILE%\.wslconfig" >> %LOG% 2>&1
docker info --format "{{.OperatingSystem}} | {{.KernelVersion}}" >> %LOG% 2>&1

echo [%time:~0,8%] 5/5 Network addresses ...
echo === [%time:~0,8%] ipconfig >> %LOG%
ipconfig | findstr /i "adapter IPv4" >> %LOG% 2>&1

echo === [%time:~0,8%] end >> %LOG%
echo.
echo [%time:~0,8%] All done. This window closes in 15 seconds.
timeout /t 15 >nul
