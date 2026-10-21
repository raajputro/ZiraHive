@echo off
rem ZiraHive test helper: writes facts about Docker on this PC to test-zh\zh-check.log (safe, changes nothing)
cd /d "%~dp0.."
(
echo === date
date /t & time /t
echo === docker version
docker version --format "client {{.Client.Version}} server {{.Server.Version}} {{.Server.Os}}"
echo === docker info
docker info --format "cpus={{.NCPU}} mem={{.MemTotal}} os={{.OperatingSystem}} driver={{.Driver}}"
echo === compose
docker compose version
echo === volumes
docker volume ls --format "{{.Name}}"
echo === containers
docker ps -a --format "{{.Names}} ^| {{.Status}} ^| {{.Image}}"
echo === images
docker images --format "{{.Repository}}:{{.Tag}} {{.Size}}"
echo === G:\Media
dir /b "G:\Media"
echo === drives
wmic logicaldisk get caption,freespace,size
echo === port 8080
netstat -ano | findstr ":8080"
echo === compose ps
docker compose ps -a
echo === end
) > test-zh\zh-check.log 2>&1
