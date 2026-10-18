ZiraHive test helpers for Windows. Double-click a .cmd file; each one runs from the
project folder and writes its log next to itself in test-zh (logs are not committed).

  zh-rebuild-all.cmd   rebuild and restart everything (server + web app)
  zh-rebuild-web.cmd   rebuild and restart only the web app
  zh-run-setup.cmd     run setup.ps1 with fixed test answers (G:\Media, AI off, firewall yes)
  zh-check.cmd         Docker facts on this PC (changes nothing)
  zh-logs.cmd          container status and recent logs (changes nothing)
  zh-net.cmd           how Windows reaches port 8080 (changes nothing)
  zh-fw.cmd            firewall, network profile and Docker networking facts (changes nothing)
  zh-parse.cmd         syntax check of setup.ps1 and update.ps1 (runs nothing)
