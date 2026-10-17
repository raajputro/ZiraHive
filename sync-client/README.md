# ZiraHive Sync for Windows

Keeps a folder on your PC and a folder in ZiraHive the same, both ways, like the Google Drive or
OneDrive app. Put a file in the folder on the PC and it appears in ZiraHive (and on your phone);
change it in ZiraHive and the PC copy updates.

## Install

1. Download **ZiraHiveSync.exe** from the latest build (GitHub > Actions > CI > Artifacts >
   `ZiraHiveSync-windows`), or build it yourself (below).
2. Run it. The first time it asks for:
   - **ZiraHive address**: your Tailscale address (`https://zirahive.<your-tailnet>.ts.net`), or
     `http://localhost:8080` on the PC that runs ZiraHive
   - your username and password (and the 6-digit code if you use two-factor sign-in)
   - the **folder on this PC** (default `C:\Users\<you>\ZiraHive`) and the **folder in ZiraHive**
     (default `/PC Sync`)
3. A small house appears next to the clock. That's it.

Windows may warn that the app is from an unknown publisher, because it isn't signed with a paid
certificate. Choose **More info > Run anyway**, or build it yourself from this source.

## What it does

| On the PC | In ZiraHive | Result |
|---|---|---|
| new or changed | unchanged | uploaded; ZiraHive keeps the old copy under Versions |
| unchanged | new or changed | downloaded |
| deleted | unchanged | moved to the ZiraHive Trash (kept 30 days) |
| unchanged | deleted | moved to the Windows Recycle Bin |
| changed | changed differently | both kept: the PC one becomes `name (PC copy 2026-10-17 21.05).ext` |

- Checks every minute; **Sync now** in the tray menu does it straight away.
- If the folder is missing (a USB drive that isn't plugged in), it does nothing.
- If one run would delete more than half of the files, it pauses and tells you. If you meant it,
  choose **Sync now, deletions included**.
- Files still being written, Office lock files (`~$...`), `desktop.ini` and `Thumbs.db` are left alone.
- The tray icon is indigo when everything is up to date, jute while syncing, red when something
  needs you, grey when paused.
- It speaks Bangla when your ZiraHive account is set to Bangla.
- The sign-in is kept in Windows Credential Manager and lasts a year. **Settings > Sign out
  everywhere** in ZiraHive, or changing your password, signs this PC out too.

## Show ZiraHive on the TV

Tick **Show on TVs at home** in the tray menu. Smart TVs on the same Wi-Fi (Samsung, LG, Sony,
Android TV, Xbox, VLC on a phone: anything that speaks DLNA) then list **ZiraHive (your PC's name)**
among their media sources, with your video categories, series by season, Continue watching and
music albums. The first time, Windows asks whether to allow the app on private networks: allow it.

- The TV sees what the signed-in account can see, and anyone on your Wi-Fi can browse it, so sign
  in with the family's account rather than the admin. Its age limits apply.
- The TV plays the files from ZiraHive directly, with links that each play one title for 12 hours.
  When this app runs on another PC than ZiraHive, set `ZIRAHIVE_LAN_URL` in ZiraHive's `.env`.
- Not on Windows? `zirahive-sync tv` runs the same on any computer at home (Linux, Mac).

## Command line

```
ZiraHiveSync.exe once                 sync once and print what happened
ZiraHiveSync.exe add D:\Work /Work    sync another folder pair
ZiraHiveSync.exe status
ZiraHiveSync.exe startup on|off       start with Windows (the set-up window does this)
ZiraHiveSync.exe tv                   show ZiraHive on TVs at home until stopped
```

Settings and a log are in `%APPDATA%\ZiraHive Sync`.

## Build it yourself

```powershell
py -3.12 -m pip install . pyinstaller
py -3.12 make_icon.py
py -3.12 -m PyInstaller --onefile --windowed --name ZiraHiveSync --icon zirahive-sync.ico zirahive_sync\__main__.py
```

The program is in `dist\ZiraHiveSync.exe`. It also runs on macOS and Linux with
`pip install .` and `zirahive-sync` (the tray needs a desktop that shows tray icons).
