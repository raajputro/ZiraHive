# First run on your PC

About 30 minutes, most of it waiting for Docker the first time.

## Before you start

- Windows 10 or 11 with **Docker Desktop** installed (free for personal use). Start it once and let
  it finish setting up WSL 2. If it asks to update WSL, run `wsl --update` in PowerShell as
  administrator and restart the PC.
- At least **20 GB free** on the drive that will hold backups (photos from phones grow quickly).
- Your media in one folder with a folder per kind inside, for example:

  ```
  G:\Media\English Movies
  G:\Media\Hindi Movies
  G:\Media\Web Series
  G:\Media\Music
  ```

## Install

1. In the ZiraHive folder, right-click **setup.ps1 > Run with PowerShell**. For the Windows
   Firewall rule (so phones can connect), run it once from PowerShell **as administrator** instead:
   `powershell -ExecutionPolicy Bypass -File setup.ps1`
2. Answer the two questions: the media folder (`G:\Media`) and whether to turn on the local AI.
3. Wait. When it says "ZiraHive is running", the browser opens. Create the admin account.
4. **Settings > Server > Health**: everything should be OK or a note. Fix anything marked with a
   warning; each one says how.
5. On your phone (same Wi-Fi), open the address setup printed, such as `http://192.168.0.105:8080`,
   and choose **Add to Home Screen**.

## Check that it all works

- [ ] **Watch** shows your categories, and a film plays (try an MKV too: it's converted as it plays)
- [ ] **Photos > Upload photos** on the phone backs up a few pictures
- [ ] **Files**: upload a PDF, then find it by a word inside it with the search box
- [ ] **Settings > Your account**: turn on two-factor sign-in, add a passkey (needs `localhost` or https)
- [ ] **Settings > People**: add your family
- [ ] **Settings > Server > Offsite backup**: back up to a USB disk or a second drive
- [ ] Optional: remote access with Tailscale ([REMOTE_ACCESS.md](REMOTE_ACCESS.md)), the TV
      ([README](../README.md#on-the-tv)), the local AI ([AI.md](AI.md))

## When something's wrong

First run the health check from PowerShell in the ZiraHive folder:

```powershell
docker compose exec api python -m app.doctor
```

| What you see | What to do |
|---|---|
| setup says Docker Desktop isn't running | Start it from the Start menu, wait for "Engine running", run setup again |
| "Port 8080 is already used" | Close the other program, or set `ZIRAHIVE_HTTP_PORT=8090` in `.env` and run setup again |
| The page doesn't open on the phone | Same Wi-Fi? Run setup once as administrator (firewall), or allow port 8080 in Windows Firewall |
| Watch is empty | Health > Media folder. Is `MEDIA_PATH` in `.env` right, with folders inside it? Then Settings > Find new folders |
| A category says its folder can't be found | The drive isn't plugged in, or its letter changed. Fix `MEDIA_PATH` and run setup again |
| Videos won't play | Health > ffmpeg. Big 4K HEVC files need time to convert on a CPU: pick 720p in the player |
| Everything is slow right after setup | The first scan reads every film and photo; give it an hour for a big library |
| Something else | `docker compose logs --tail 100 api worker` shows what ZiraHive is saying |

## Updating later

Right-click **update.ps1 > Run with PowerShell**. It gets the new version (when the folder came
from git), rebuilds and restarts, and the database is upgraded by itself. Your files, settings and
accounts stay. A backup first never hurts: **Settings > Server > Offsite backup > Back up now**.
