# ZiraHive

**Your own Google Drive and Jellyfin, on your own PC.** Back up phones, keep your files, and watch
your movies, series, music and books on any screen in the house, or anywhere with your family.
Free, open source and private: nothing leaves your home unless you share it.

Everything runs in the web browser on phones, PCs and TVs. There are no apps to install from a
store.

> **Status:** version 1.0: all nine planned batches are done. Installing it for the first time?
> Follow [docs/FIRST_RUN.md](docs/FIRST_RUN.md). What's next: [docs/ROADMAP.md](docs/ROADMAP.md).

## Contents

- [What it does](#what-it-does)
- [Get started on Windows](#get-started-on-windows)
- [Your media](#your-media)
- [Watching](#watching)
- [Listening and reading](#listening-and-reading)
- [Photos, files and sharing](#photos-files-and-sharing)
- [On your phone](#on-your-phone)
- [Away from home](#away-from-home)
- [Keeping it safe](#keeping-it-safe)
- [Local AI](#local-ai-optional)
- [Plugins](#plugins)
- [Running it day to day](#running-it-day-to-day)
- [For developers](#for-developers)

## What it does

| | |
|---|---|
| **Backup** | The phone's camera roll and any files, with uploads that resume after a dropped connection. Photos already saved are skipped. |
| **Photos** | A timeline by date, "On this day" memories, albums to share with family, iPhone HEIC photos shown in every browser. Clean up duplicates and blurry shots. |
| **Local AI** (optional) | Search photos by what's in them, People grouped by face, subtitles for films without them, and questions answered from your documents. All on your PC. |
| **Files** | Folders, a 30-day trash, and version history: upload a document with the same name and the old copy is kept. |
| **Search and scan** | Find documents by the words inside them, in Bangla and English, even in scanned papers. Turn paper into a searchable PDF with the phone's camera. |
| **Watch** | Movies and series from your own folders, with posters, seasons, "next episode" and skip intro. Every format plays: what the browser can't play is converted while you watch. |
| **Watch parties** | Watch together from different places, in step, with chat, reactions and voice chat. |
| **Linked servers** | Share some categories with family who have their own ZiraHive, and watch theirs. |
| **On the TV** | Cast to a Chromecast, or browse ZiraHive from any smart TV's media menu (DLNA). |
| **Listen** | Music by album and artist, playlists, and audiobooks that remember where you stopped. |
| **Read** | EPUB and PDF books and comics, with your page saved on every device. |
| **Vault** | A locked space for ID scans and private papers, encrypted on your device. Not even the admin can open it. |
| **PC sync** | The ZiraHive Sync app keeps a folder on your Windows PC and in ZiraHive the same, both ways. |
| **Family** | An account for each person, storage limits, and age limits for children. |
| **Passkeys** | Sign in with your phone's or laptop's fingerprint, face or screen lock. |
| **Plugins** | Add-ons for Telegram messages, webhooks to Home Assistant or n8n, or your own. |
| **বাংলা** | The whole interface in Bangla, with Bangla digits and dates. |

## Get started on Windows

You need **Docker Desktop** (free for personal use) with the WSL 2 backend. Install it and start
it once.

1. **Run the setup.** In this folder, right-click **setup.ps1** and choose **Run with PowerShell**
   (run it as administrator once, so it can let phones through Windows Firewall). It asks where
   your media folder is, for example `G:\Media`, and whether to turn on the local AI. Then it:
   - creates `.env` with a random database password,
   - puts ZiraHive's own data (backed-up photos, files, the database) on the drive with the most
     free space,
   - shows which categories your media folders will become,
   - fills in this PC's home-network address for TVs,
   - starts Docker Desktop if needed, checks the port and the free space,
   - builds and starts everything (10 to 20 minutes the first time), waits until it answers, and
     opens it, with a ZiraHive shortcut on the desktop.

2. **Create the admin account** at **http://localhost:8080**.

3. **Check its health** in **Settings > Server > Health**: each item is OK, or says what to do.

4. **Open it on other devices at home.** Use the address setup printed, for example
   `http://192.168.0.105:8080`. If it doesn't load, allow ZiraHive through Windows Firewall, in
   PowerShell as administrator:

   ```powershell
   New-NetFirewallRule -DisplayName "ZiraHive" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow
   ```

   Give the PC a fixed address in your router (often called "DHCP reservation") so it never changes.

5. **Add your family** in **Settings > People**, and turn on two-factor sign-in for yourself in
   **Settings > Your account**.

Prefer doing it by hand? `copy .env.example .env`, fill in `POSTGRES_PASSWORD`,
`ZIRAHIVE_DATA_PATH` and `MEDIA_PATH`, then run `docker compose up -d --build`.

## Your media

### The media folder

ZiraHive reads your media **where it already is**. Nothing is copied, moved or changed, and it
can't see any other folder or drive.

Every folder inside your media folder becomes a category by itself, named and typed from the
folder name:

```
G:\Media\English Movies   -> "English Movies"  movies
G:\Media\hindi_movies     -> "Hindi Movies"    movies
G:\Media\Web Series       -> "Web Series"      series
G:\Media\Animation        -> "Animation"       movies and series
G:\Media\Music            -> "Music"           music
G:\Media\Audiobooks       -> "Audiobooks"      audiobooks
G:\Media\Ebooks           -> "Ebooks"          books
G:\Media\Comics           -> "Comics"          comics
```

- Rename a category, change its type, set its order or an age rating in **Settings > Server >
  Categories**.
- A new folder is added by itself overnight, or straight away with **Find new folders**.
- Every category is scanned again each night, and when you press **Scan now**.
- To use a different media folder, run `setup.ps1` again. It's `MEDIA_PATH` in `.env`.

**Media in more than one place?** Share that whole drive (read-only) by adding a line like
`DRIVE_E=E:/` to `.env` and running `docker compose up -d`. Then add any folder on it in
**Settings > Server > Categories > Choose folder**. Only drives you list are visible. A category
whose drive is unplugged is hidden until it's back.

### Category types

| Type | Use for | How files are read |
|---|---|---|
| Movies | English, Hindi, Bangla movies | every video is a movie |
| Series | Web Series, TV Shows, Natok | every video is an episode, grouped by the show's folder |
| Movies and series | Animation, Kids | names like `S01E02` are episodes, the rest are movies |
| Music | Music, Bangla Songs, Rabindra Sangeet | every audio file is a song; one folder with one album tag is an album |
| Audiobooks | Audiobooks | one file is one book; a folder of files (CD1/CD2 too) is one book in parts |
| Books | Ebooks, Novels | EPUB and PDF; series from Calibre's metadata |
| Comics | Comics, Manga | CBZ, CBR, CB7, CBT, or a folder of page pictures |

### Naming files

- **Movies:** `Movie Name (2019).mkv` or the common `Movie.Name.2019.1080p.mkv` both work. Samples
  and trailers are skipped.
- **Episodes:** `S01E02`, `1x02`, `E03`, `Episode 7` or a leading number (`01 - Pilot.mkv`). The
  season comes from the name or a `Season 2` folder.
- **Music:** the tags inside the files (title, artist, album, track, cover). Files without tags
  still work: the album comes from the folder name, the artist from the folder above, and a
  `cover.jpg` or `folder.jpg` becomes the cover.
- **Subtitles:** inside the file, or a file next to it with the same name: `Movie.srt`,
  `Movie.en.srt`, `Movie.bn.srt`.
- **Posters and plot summaries:** add a free key from themoviedb.org as `ZIRAHIVE_TMDB_API_KEY` in
  `.env`. Without it, a frame from the video becomes the poster.

## Watching

### Playing anything

- **Files the browser can play** (MP4 with H.264, WebM) play as they are.
- **Everything else** (MKV with AC-3 or DTS sound, HEVC, AVI, ...) is converted while you watch.
  You can still jump anywhere in the film; ZiraHive converts from that point.
- **Quality:** Original, 1080p, 720p, 480p or 360p. **Low-data mode** (Settings > Your account)
  starts videos at 480p.
- **Audio and subtitles:** every audio track is listed by language, handy for dual-audio releases.
- **Skip intro and next episode:** files with chapters called Intro or Credits get the buttons by
  themselves. For a series without chapters, an admin sets **Intro and credits** once on the
  series page. When the credits start, the next episode counts down and plays.
- **Watch offline:** **Make a copy** under the player creates a smaller MP4 to download to a phone
  or laptop (480p is about 1 to 1.5 GB for a two-hour film).
- **Another player:** **Open in another player** gives a link for VLC, valid for 24 hours.
- **NVIDIA GPU:** converting works on the CPU, but a GPU makes it effortless. Uncomment the
  `deploy` block under `api` and `worker` in `docker-compose.yml`.

### Watch parties

Press **Watch together** on any movie or episode, start now or pick a time, and invite family or
friends. Everyone's video stays in step. Anyone (or only the host) can pause and skip, the party
waits when someone's video is loading, and there's chat, emoji reactions and "next episode for
everyone". Each person still picks their own quality, audio and subtitles.

**Voice chat:** press **Join voice chat** in the party. Everyone who joins hears each other, with a
glowing mic next to whoever is talking, and the film turns down while people talk. Devices talk to
each other directly and encrypted (WebRTC); it needs a secure page (your `https://` Tailscale
address, or `http://localhost` on the PC) and the browser's microphone permission.

### Linked ZiraHive servers

Your brother has his own ZiraHive? Share some categories with each other.

1. On yours, **Settings > Server > Linked ZiraHive servers > Share with another ZiraHive**: name it,
   tick the categories, choose an age limit, and enter your address as his server can reach it
   (your public share address `https://…ts.net:8443`, or your Tailscale address if his server is
   on your Tailscale). Press **Make a link code** and send him the code privately.
2. On his, paste the code under **Watch another ZiraHive**.

His family then sees your categories on their Watch page, marked "from ...", and plays them like
their own. His server fetches the films for them: nobody gets an account on yours, and his
server can reach only the categories you ticked. Where each person stopped is kept on his side.
Remove the link on your side and it stops at once. Set `ZIRAHIVE_SERVER_NAME` in `.env` for the
name his side sees.

### On the TV

- **Chromecast**, and TVs with Chromecast built in (most Android and Google TVs): press **Cast to
  TV** under the player in Chrome or Edge. The TV fetches the film from ZiraHive by itself, and the
  page becomes the remote. Casting needs a secure page, as Google requires: open ZiraHive at
  `http://localhost:8080` on the PC itself, or at your Tailscale `https://` address on a phone.
- **Other smart TVs** (Samsung, LG, Sony, ...) use **DLNA**. In the ZiraHive Sync app on the PC,
  tick **Show on TVs at home**. The TV's media or source menu then lists *ZiraHive (your PC)* with
  your categories, series by season and music albums. Anyone on your Wi-Fi can browse what the
  signed-in account can see, so sign the app in with a family account rather than the admin.
- **iPhone, iPad, Mac:** AirPlay from the video's own controls.

Both need this PC's home-network address as `ZIRAHIVE_LAN_URL` in `.env`; `setup.ps1` fills it in.
Links given to a TV play only that one title, for 12 hours.

### Live TV (IPTV)

Got an IPTV subscription (Xtream Codes: a server address, username and password)? Open **Live TV**
and add it. You get channels by category with the programme guide, movies and series, favourites,
and channel up / down with the arrow keys, all through ZiraHive, so the login never reaches a
browser and one channel watched on several screens counts as one connection. Admins can share a
subscription with the family. Details: [docs/IPTV.md](docs/IPTV.md).

### Age limits for children

1. In **Settings > People**, edit the child's account and choose **Only rated 7+ or younger** (or
   13+).
2. Give titles an age. With a TMDB key, movies and series get their certificate automatically
   (India's CBFC first, then the US and UK). For a whole category, choose **Suits 7+** next to it in
   **Settings > Server**. An admin can also set the age on any single title.
3. Titles without any age are hidden from limited profiles, to be safe. Live TV (IPTV) is hidden
   from them too, since channels carry no ages.

## Listening and reading

- **The player** sits along the bottom and keeps playing while you browse. Tap it for the queue or
  chapters. On phones, the lock screen and Bluetooth headsets can pause and skip.
- **Audiobooks** save your place as you listen, so you can stop on the phone and carry on from the
  PC. Speed 0.75× to 2×, and a sleep timer.
- **Formats:** MP3, AAC/M4A/M4B, FLAC, Ogg and Opus play as they are. WMA, ALAC, APE and AIFF are
  converted to MP3 the first time they play.
- **Books** open on the page you left, on any device, with your choice of text size, font and page
  colour. **Download** saves the original for an e-reader.
- **Comics** load pages sized for your screen. Manga can read right to left, and webtoons scroll
  down.

## Photos, files and sharing

- **Albums:** in Photos, press **Select**, pick photos and choose **Add to album**. **Share with
  family** lets other accounts see it, and add their own photos if you allow.
- **Links:** the link button on any file, folder or album makes a link anyone can open, with an
  optional password, an end date and a view-only mode. Visitors don't need an account.
- **Versions:** in Files, uploading a document with the same name into the same folder keeps the
  old copy (the clock button shows them). Photos are never versioned, because phones reuse names
  like `IMG_0001.JPG`.
- **Search:** the search box in Files finds documents by the words inside them: PDFs, Word,
  PowerPoint, OpenDocument and text files, and the text in scanned PDFs and photos of pages, in
  Bangla and English. `ZIRAHIVE_OCR=all` in `.env` also reads every photo (slower); `off` turns it
  off.
- **Scan:** **Scan** in Files turns paper into a searchable PDF with the phone's camera. ZiraHive
  finds the page, straightens it and cleans it up; add as many pages as you like.
- **Vault:** for papers no one else should see. Files are encrypted on your device with your own
  passphrase before upload. Keep the recovery key you're shown somewhere safe: without the
  passphrase or the key, nobody can open the vault, including you.
- **PC sync:** the ZiraHive Sync app for Windows keeps a folder on your PC and one in ZiraHive the
  same, both ways. See [sync-client/README.md](sync-client/README.md).

Backed-up files are stored under readable names in `ZIRAHIVE_DATA_PATH\storage\<username>\...`, so
you can browse them in Explorer even when ZiraHive isn't running.

## On your phone

Open your ZiraHive address and choose **Add to Home Screen** (Safari: the Share button; Chrome: the
menu). It then opens full screen with its own icon, like an app.

**Back up the camera roll:** **Photos > Upload photos**, then pick everything. Photos already
saved are skipped, and uploads continue where they stopped. You can lock the phone: the upload
pauses and carries on when you open ZiraHive again, and you're notified when it finishes or a file
fails. On iPhone, Safari may hand over JPEG copies of HEIC photos and only the still part of Live
Photos; to keep the originals, copy them to a PC first and upload from there.

**Notifications:** install the free **ntfy** app, subscribe to a topic with a long random name
(for example `zirahive-k2v9x7q`), paste `https://ntfy.sh/zirahive-k2v9x7q` into **Settings > Your
account > Phone notifications**, and press **Send test**.

## Away from home

ZiraHive is reached from outside through **Tailscale**: free, encrypted, no router changes, and it
works behind the CGNAT most Bangladeshi internet providers use. The app itself is never on the
public internet; only your devices and your family's can reach the sign-in page.

1. Make a free account at https://login.tailscale.com. In its admin console, under **DNS**, keep
   **MagicDNS** on and press **Enable HTTPS**.
2. Under **Settings > Keys**, generate an auth key and put it in `.env` as `TS_AUTHKEY=...`.
3. Run `docker compose --profile remote up -d --build`. The PC appears as something like
   `zirahive.tail1234.ts.net`.
4. On each phone and laptop, install the Tailscale app, sign in, and open
   `https://zirahive.tail1234.ts.net`.
5. Invite family under **Users** in the Tailscale console (the free plan covers 6 people).

Share links can get their own public address that serves share links and nothing else.
[docs/REMOTE_ACCESS.md](docs/REMOTE_ACCESS.md) has the full guide, including that and the other
options.

## Keeping it safe

- **Sign-in:** passkeys (**Settings > Your account > Passkeys**), two-factor sign-in with recovery
  codes, "sign out everywhere", password changes end other sessions, slowed-down password
  guessing, and an activity log for the admin. A passkey works on the address it was made on, so
  add one on each address you use (for example on your Tailscale address).
- **Security check:** **Settings > Server > Security check** lists anything that needs attention.
- **Offsite backup:** a daily encrypted copy of photos, files, the vault and the database to a USB
  disk, another computer or a cloud bucket, with regular checks. Set it up in **Settings > Server >
  Offsite backup**; restoring is in [docs/BACKUP.md](docs/BACKUP.md).
- **Your media is read-only** to ZiraHive: it can never change or delete it.

## Local AI (optional)

```powershell
docker compose --profile ai up -d --build
```

turns on free AI models that run on your PC; nothing is sent anywhere. Then:

- **Photos > search**: "beach at sunset", "birthday cake", "লাল গাড়ি".
- **Photos > People**: photos grouped by face. Give people names, fix mistakes, merge doubles.
- **Make subtitles with AI** in the player (admins): Whisper listens to a film and writes subtitles.
- **Files > Ask**: "When does my passport expire?" answered from your own documents, with where it
  was found.

**Photos > Clean up** (duplicates and blurry photos) works without AI. See [docs/AI.md](docs/AI.md)
for memory needs, model choices and graphics cards.

## Plugins

**Settings > Server > Plugins** has two built in:

- **Telegram messages**: a message when new movies arrive, a backup fails or a watch party starts.
- **Webhook**: every event as signed JSON to Home Assistant, n8n, Node-RED or your own script.

You can write your own in a few lines of Python; see [docs/PLUGINS.md](docs/PLUGINS.md).

## Running it day to day

**Updating:** right-click **update.ps1 > Run with PowerShell**. Your files, settings and
accounts stay, and the database is upgraded by itself.

```powershell
docker compose ps                              # what's running
docker compose exec api python -m app.doctor   # health check, also when the page won't open
docker compose logs -f api worker              # watch the logs
docker compose down                            # stop (your data stays in ZIRAHIVE_DATA_PATH)
```

The admin dashboard in **Settings > Server** shows who is watching what, background jobs, and free
space on every disk.

## For developers

### How it fits together

| Container | Does |
|---|---|
| `web` | Caddy: serves the web app and proxies `/api` |
| `api` | FastAPI (Python): accounts, uploads, files, photos, media, streaming |
| `worker` | Background jobs: thumbnails, scans, text reading, backups, nightly cleanup |
| `postgres` | Database (with pgvector, ready for AI search) |
| `redis` | Job queue between `api` and `worker` |
| `tailscale` | Remote access, only with `--profile remote` |
| `ai` | Local AI: CLIP, faces, Whisper; only with `--profile ai` |
| `ollama` | Local language models for Ask; only with `--profile ai` |

### Running from source

```powershell
# server (Python 3.12+)
cd server
python -m venv .venv; .venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000   # SQLite and in-process jobs, no Docker needed

# web (Node 20+), in a second terminal
cd web
npm install
npm run dev                                 # http://localhost:5173, proxies /api to :8000
```

Without `ZIRAHIVE_DATABASE_URL` and `ZIRAHIVE_REDIS_URL`, the server uses SQLite in `server/data` and
runs background jobs inside the API process. The database is upgraded by Alembic migrations when
the server starts; after changing `app/models.py`, add one with
`alembic revision --autogenerate -m "what changed"` (a test fails until you do). Video features need `ffmpeg` on your PATH
(`winget install ffmpeg`). API docs are at http://localhost:8000/docs while the server runs.

Every text in the interface needs a Bangla translation in `web/src/locales/bn.ts`;
`npm run check:i18n` lists any that are missing.

### Testing

| What | Where | Run |
|---|---|---|
| API tests (pytest; set `TEST_POSTGRES_URL` to also check the migrations on PostgreSQL) | `server/tests` | `cd server; pytest` |
| Local AI helper, with the real face models | `ai/tests` | `pytest ai/tests` |
| End-to-end tests in a real browser (Playwright) | `e2e/tests` | see below |
| Load test (Locust) | `loadtest/locustfile.py` | see the file's header |

End-to-end tests run against a running ZiraHive. On a fresh install they create the admin account
themselves; on yours, pass your admin sign-in:

```powershell
cd e2e
npm install
npx playwright install chromium chrome
$env:E2E_BASE_URL="http://localhost:8080"; $env:E2E_ADMIN="mahbub"; $env:E2E_PASSWORD="..."
npx playwright test          # then: npx playwright show-report
```

The player tests need real Google Chrome, because open-source Chromium can't decode H.264; they
skip themselves otherwise. Tests make their own uniquely named data, so they're safe against your
real server, though test users and folders stay afterwards.

GitHub Actions (`.github/workflows/ci.yml`) runs the API tests, builds the web app, the Docker
images and the Windows sync app, then starts the full stack with sample media
(`scripts/make-sample-media.sh`) and runs the Playwright suite on every push.

## Upgrading from GharBox

ZiraHive used to be called GharBox. To upgrade an existing install, get the new code and run
`setup.ps1` again. It renames the `GHARBOX_` settings in `.env` to `ZIRAHIVE_`, keeps your database
and Tailscale sign-in, stops the old containers and starts ZiraHive. Your files, photos, accounts
and watch history stay as they were, and people stay signed in at home. Two things to know:

- Your Tailscale address becomes `https://zirahive.<your-tailnet>.ts.net` (setup updates
  `ZIRAHIVE_PUBLIC_URL`). Everyone signs in once more there, and share links made with the old
  `gharbox` address need sharing again.
- The PC app is now **ZiraHiveSync.exe**; it picks up the old app's folders and sign-in by itself.
  Remove GharBoxSync.exe from Windows start-up and run `ZiraHiveSync.exe startup on`.

Your data folder can keep its old name (`GharBoxData`); it's just the path in `.env`.

## License

AGPL-3.0, so ZiraHive stays free: anyone who runs a modified version as a service must share their
changes.
