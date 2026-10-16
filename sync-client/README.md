# GharBox Sync for Windows

Keeps a folder on your PC and a folder in GharBox the same, both ways, like the Google Drive or
OneDrive app. Put a file in the folder on the PC and it appears in GharBox (and on your phone);
change it in GharBox and the PC copy updates.

## Install

1. Download **GharBoxSync.exe** from the latest build (GitHub > Actions > CI > Artifacts >
   `GharBoxSync-windows`), or build it yourself (below).
2. Run it. The first time it asks for:
   - **GharBox address**: your Tailscale address (`https://gharbox.<your-tailnet>.ts.net`), or
     `http://localhost:8080` on the PC that runs GharBox
   - your username and password (and the 6-digit code if you use two-factor sign-in)
   - the **folder on this PC** (default `C:\Users\<you>\GharBox`) and the **folder in GharBox**
     (default `/PC Sync`)
3. A small house appears next to the clock. That's it.

Windows may warn that the app is from an unknown publisher, because it isn't signed with a paid
certificate. Choose **More info > Run anyway**, or build it yourself from this source.

## What it does

| On the PC | In GharBox | Result |
|---|---|---|
| new or changed | unchanged | uploaded; GharBox keeps the old copy under Versions |
| unchanged | new or changed | downloaded |
| deleted | unchanged | moved to the GharBox Trash (kept 30 days) |
| unchanged | deleted | moved to the Windows Recycle Bin |
| changed | changed differently | both kept: the PC one becomes `name (PC copy 2026-10-17 21.05).ext` |

- Checks every minute; **Sync now** in the tray menu does it straight away.
- If the folder is missing (a USB drive that isn't plugged in), it does nothing.
- If one run would delete more than half of the files, it pauses and tells you. If you meant it,
  choose **Sync now, deletions included**.
- Files still being written, Office lock files (`~$...`), `desktop.ini` and `Thumbs.db` are left alone.
- The tray icon is indigo when everything is up to date, jute while syncing, red when something
  needs you, grey when paused.
- It speaks Bangla when your GharBox account is set to Bangla.
- The sign-in is kept in Windows Credential Manager and lasts a year. **Settings > Sign out
  everywhere** in GharBox, or changing your password, signs this PC out too.

## Show GharBox on the TV

Tick **Show on TVs at home** in the tray menu. Smart TVs on the same Wi-Fi (Samsung, LG, Sony,
Android TV, Xbox, VLC on a phone: anything that speaks DLNA) then list **GharBox (your PC's name)**
among their media sources, with your video categories, series by season, Continue watching and
music albums. The first time, Windows asks whether to allow the app on private networks: allow it.

- The TV sees what the signed-in account can see, and anyone on your Wi-Fi can browse it, so sign
  in with the family's account rather than the admin. Its age limits apply.
- The TV plays the files from GharBox directly, with links that each play one title for 12 hours.
  When this app runs on another PC than GharBox, set `GHARBOX_LAN_URL` in GharBox's `.env`.
- Not on Windows? `gharbox-sync tv` runs the same on any computer at home (Linux, Mac).

## Command line

```
GharBoxSync.exe once                 sync once and print what happened
GharBoxSync.exe add D:\Work /Work    sync another folder pair
GharBoxSync.exe status
GharBoxSync.exe startup on|off       start with Windows (the set-up window does this)
GharBoxSync.exe tv                   show GharBox on TVs at home until stopped
```

Settings and a log are in `%APPDATA%\GharBox Sync`.

## Build it yourself

```powershell
py -3.12 -m pip install . pyinstaller
py -3.12 make_icon.py
py -3.12 -m PyInstaller --onefile --windowed --name GharBoxSync --icon gharbox-sync.ico gharbox_sync\__main__.py
```

The program is in `dist\GharBoxSync.exe`. It also runs on macOS and Linux with
`pip install .` and `gharbox-sync` (the tray needs a desktop that shows tray icons).
