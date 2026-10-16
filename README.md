# GharBox

Your own Google Drive + Jellyfin, running on your PC. Free, open source, and private: your
photos, documents and movies never leave your home. Everything works in a web browser, on
your PC, phone and TV.

- **Backup**: phone camera roll and any files, with resumable uploads. Photo backup skips
  anything already saved
- **Photos**: timeline grouped by date, "On this day" memories, albums you can share with
  family, full-screen previews that work for iPhone HEIC in every browser
- **Files**: folders, rename, move, download, a 30-day trash, and version history: upload a
  document with the same name and the old copy is kept (last 20)
- **Sharing**: links for a file, folder or album, with an optional password, an expiry date and
  a view-only mode. Visitors don't need an account
- **Watch**: one category per folder (English Movies, Hindi Movies, Bangla Movies, Web Series,
  Animation, ...). Movies get titles, years and posters; web series get seasons, episodes and
  "next episode". Every format plays in the browser: anything the browser can't play is converted
  on the fly. Pick the quality (down to 360p for mobile data), the audio language and subtitles,
  skip intros, and download a smaller copy to watch offline
- **Watch parties**: press Watch together on any movie or episode, start now or pick a time, and
  invite family or friends. Everyone's video stays in step, anyone (or only the host) can pause and
  skip, the party waits when someone's video is loading, and there's chat, emoji reactions and
  "next episode for everyone". Each person still picks their own quality, audio and subtitles
- **Listen**: music by album, artist and song, favourites, playlists, shuffle and repeat, and a
  player that keeps going while you browse, with lock-screen and headset controls on phones.
  Audiobooks remember where you stopped, with chapters, speed and a sleep timer. WMA, ALAC and
  other formats browsers can't play are converted once, by themselves
- **Read**: EPUB and PDF books and comics (CBZ, CBR, CB7, or a folder of page pictures) in the
  browser, with your place saved on every device. Light, sepia and dark pages, text size, a contents
  list, right-to-left for manga and a scrolling mode for webtoons
- **Kids**: give a profile an age limit and it only sees titles rated for that age
- **Family**: several accounts with their own private space, admin and member roles, and
  storage limits
- **Security**: two-factor sign-in with recovery codes, "sign out everywhere", password changes
  end other sessions, slowed-down password guessing, and an activity log for the admin
- **Notifications**: a bell in the app for backups, shared albums, new movies and a nearly full
  disk, and on your phone through the free ntfy app
- **Admin dashboard**: who is watching what, background jobs, and free space on every disk

> Status: milestone 1, batches 1 to 4 and remote access. Next up: an encrypted vault, encrypted
> offsite backup, a Bangla interface and a PC sync client. See [docs/ROADMAP.md](docs/ROADMAP.md).

## How it fits together

| Container | Does |
|---|---|
| `web` | Caddy: serves the web app, proxies `/api`, does HTTPS when you give it a domain |
| `api` | FastAPI server (Python): logins, uploads, files, photos, movies, streaming |
| `worker` | Background jobs: thumbnails, movie scans, nightly trash cleanup |
| `postgres` | Database (includes pgvector, ready for AI search later) |
| `redis` | Job queue between `api` and `worker` |
| `ollama` | Optional local AI, only with `--profile ai` |

## Run it on Windows

You need **Docker Desktop** (free for personal use) with the WSL 2 backend.

1. Open PowerShell in this folder and create your settings file:

   ```powershell
   copy .env.example .env
   notepad .env
   ```

   Set at least:
   - `POSTGRES_PASSWORD`: letters and numbers. Make one with
     `python -c "import secrets; print(secrets.token_hex(24))"`
   - `GHARBOX_DATA_PATH`: where backups go, for example `D:/GharBoxData` (use forward slashes)
   - `MEDIA_PATH`: your media folder, for example `D:/Media` (see [Watch categories](#watch-categories))

2. Start everything:

   ```powershell
   docker compose up -d --build
   ```

   The first build takes a few minutes. Check that it's healthy with `docker compose ps`.

3. Open **http://localhost:8080** and create the admin account.

4. To use it from your phone or TV, find your PC's address with `ipconfig` (the IPv4 address,
   such as `192.168.0.105`) and open `http://192.168.0.105:8080`. If it doesn't load, allow
   port 8080 through Windows Firewall:

   ```powershell
   New-NetFirewallRule -DisplayName "GharBox" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow
   ```

   Tip: give your PC a fixed address in your router's DHCP settings so this never changes.

### Everyday commands

```powershell
docker compose ps                 # what's running
docker compose logs -f api worker # watch the logs
docker compose pull; docker compose up -d --build   # update after pulling new code
docker compose down               # stop (your data stays in GHARBOX_DATA_PATH)
```

Your backed-up files are stored under readable names in
`GHARBOX_DATA_PATH/storage/<username>/...`, so you can still browse them in Explorer even
if GharBox is not running.

## On your phone

GharBox runs in the phone's browser, so there's no app to install from a store. Open your GharBox
address and choose **Add to Home Screen** (Safari: Share button; Chrome: menu). It then opens full
screen with its own icon, like an app.

To back up your camera roll, open **Photos > Upload photos** and pick everything you want. Files
already saved are skipped, and uploads continue where they stopped if the connection drops. You can
lock the phone: the browser pauses the upload and carries on when you open GharBox again. When a
backup finishes, or a file fails, you get a notification (on the phone too, with ntfy set up), so
there's no need to keep the screen on. On iPhone, Safari may hand over JPEG copies of HEIC photos and only the still
image of Live Photos; to keep the originals, copy them to a PC first and upload from there.

## Watch categories

Make one folder per category inside your media folder. Each one becomes a tab and a row on the
Watch page, in the order you choose in Settings:

```
D:/Media/
  English Movies/
    Inception (2010)/Inception (2010).mkv
    The.Matrix.1999.1080p.BluRay.mkv
  Hindi Movies/
  Bangla Movies/
  Web Series/
    Mirzapur/
      Season 1/Mirzapur.S01E01.mkv
      Season 2/Mirzapur.S02E01.mkv
    Karnaphuli/Karnaphuli.S01E01.mp4
  Animation/
    Kung Fu Panda (2008).mkv
    Avatar The Last Airbender/Book 1/Avatar.S01E01.mkv
  Music/
    Shonar Band/Monsoon Songs (2021)/01 - Rain on Tin.mp3
  Audiobooks/
    The River Journey.m4b
    Rabindra Thakur/Short Stories/01 The Postmaster.mp3, 02 Kabuliwala.mp3, ...
  Ebooks/
    Nadi Writer/The River Journey.epub
    Cooking with Mustard Oil.pdf
  Comics/
    Sky Rider/Sky Rider 001.cbz
    Hero Academy/Chapter 001/001.jpg, 002.jpg, ...
```

GharBox finds new folders on start, every night, and when you press **Find new folders** in
Settings. Folder names like `english_movies` are tidied to "English Movies". Each category has a
type, guessed from its name and changeable in Settings:

| Type | Use for | How files are read |
|---|---|---|
| Movies | English, Hindi, Bangla movies | every file is a movie |
| Series | Web Series, TV Shows, Natok | every file is an episode, grouped by the show's folder |
| Movies and series | Animation, Kids | files named like `S01E02` are episodes, the rest are movies |
| Music | Music, Bangla Songs, Rabindra Sangeet | every audio file is a song; songs in one folder with the same album tag are an album |
| Audiobooks | Audiobooks | one file is one book; a folder of files (CD1/CD2 folders too) is one book in parts |
| Books | Ebooks, Novels | EPUB and PDF; series from Calibre's metadata |
| Comics | Comics, Manga | CBZ, CBR, CB7, CBT, or a folder of page pictures; series and issue from the name or ComicInfo.xml |

Music uses the tags inside the files (title, artist, album, track number, year, cover picture). Files
without tags still work: the song name comes from the file name, the album from its folder and the
artist from the folder above, and a `cover.jpg` or `folder.jpg` next to the songs becomes the cover.

Episodes are recognised from `S01E02`, `1x02`, `E03`, `Episode 7` or a leading number
(`01 - Pilot.mkv`), with the season taken from the name or a `Season 2` / `Book 2` folder.
When an episode ends, the next one starts by itself, and Continue watching shows the next
episode of every series you're following.

A category on another drive: mount it in `docker-compose.yml` (there's a commented example
under the `api` volumes), restart, then use **Add a folder from another drive** in Settings.

### Playing anything

- **Files the browser can play** (MP4 with H.264, WebM) play as they are, with seeking.
- **Everything else** (MKV with AC-3/DTS sound, HEVC, AVI, ...) is converted while you watch.
  The seek bar still shows the whole film and you can jump anywhere; GharBox converts from that
  point. Conversion pauses when it's far ahead of you and stops when nobody is watching.
- **Quality**: Original, 1080p, 720p, 480p or 360p. With **Low-data mode** on (Settings > Your
  account) videos start at 480p.
- **Audio and subtitles**: every audio track is listed by language (handy for dual-audio Hindi and
  Bangla releases). Subtitles come from inside the file or from a file next to it with the same name:
  `Movie.srt`, `Movie.en.srt`, `Movie.bn.srt`. Picture-based subtitles (Blu-ray PGS) aren't shown yet.
- **Watch offline**: under the player, **Make a copy** creates a smaller MP4 (480p is about 1 to 1.5 GB for a
  two-hour film). You get a notification when it's ready, then **Save file** downloads it to your phone or
  laptop. Copies nobody has used for 14 days are deleted.
- **Skip intro and next episode**: files with chapters called Intro or Credits get the buttons
  automatically. For a series without chapters, an admin opens the series and sets **Intro and credits**
  once for all episodes. When the credits start, the next episode counts down from 10 and plays.
- **NVIDIA GPU**: converting on the CPU works, but a GPU makes it effortless. Uncomment the `deploy`
  block under `api` (and `worker`) in `docker-compose.yml`. Settings > Server shows which is used.

### Listening and reading

- **The player** sits along the bottom and keeps playing while you look at photos or files. Tap it
  for the big view with the queue (music) or chapters (audiobooks). On phones the lock screen and
  Bluetooth headsets can pause, skip and seek.
- **Audiobooks** save your place every few seconds and when you pause, so you can stop on the phone
  and carry on from the PC. Speed goes from 0.75× to 2×; the sleep timer stops after some minutes
  or at the end of the chapter.
- **Formats**: MP3, AAC/M4A/M4B, FLAC, Ogg and Opus play as they are. WMA, ALAC, APE and AIFF are
  converted to MP3 the first time they play (a few seconds for a song). If a browser can't play a
  file it should (some Linux browsers have no AAC), GharBox converts that one too.
- **Books** open on the page you left, on any device. EPUB text size, font and page colour are up to
  you; PDFs show one page at a time, sharp on phones. **Download** saves the original file for an
  e-reader.
- **Comics** load pages sized for your screen (smaller with Low-data mode) and remember the page.
  Manga marked right-to-left in ComicInfo.xml open that way; you can switch any comic in the reading
  settings, and choose **Scroll down** for webtoons.
- Reading CBR/CB7 comics and showing PDF covers use `bsdtar` and `pdftoppm`, which the Docker image
  includes.

### Age limits for kids

1. **Settings > People**, edit the child's account, choose **Only rated 7+ or younger** (or 13+).
2. Give titles an age. With a TMDB key, movies and series get their certificate automatically
   (India's CBFC first, then the US and UK). For whole categories, pick **Suits 7+** next to e.g.
   Animation in **Settings > Server**. An admin can also set any single title on its page.
3. Titles without any age are hidden from limited profiles, to be safe.

### Movie files

- Name files like `Movie Name (2019).mkv`, or the common `Movie.Name.2019.1080p.mkv` style;
  both are recognised. Samples and trailers are skipped.
- For posters and plot summaries, add a free TMDB key as `GHARBOX_TMDB_API_KEY`. Without it,
  GharBox uses a frame from the movie as the poster.
- Browsers play MP4/WebM with H.264, VP9 or AV1. Other files (for example HEVC in MKV)
  show a copyable link you can open in VLC on your PC, phone or TV until transcoding lands.
- Categories rescan every night at 03:00, or press the scan button in Settings.

## Sharing and family

- **Albums**: in Photos, press **Select**, pick photos and choose **Add to album**. In the album,
  **Share with family** lets other GharBox accounts see it, and add their own photos if you allow.
- **Links**: the link button on any file, folder or album makes a link anyone can open. Add a
  password, choose when it stops working, and untick **Allow downloads** for view-only (photos are
  then shown as previews and the original is never handed out).
- **Uploading again**: in **Files**, a document with the same name in the same folder becomes a
  new version (see the clock button). Photos are never versioned, because phones reuse names like
  `IMG_0001.JPG`. Uploading the same file into a different folder keeps a separate copy.

## Notifications on your phone

Install the free **ntfy** app (Android or iPhone), subscribe to a topic with a long random name,
for example `gharbox-k2v9x7q`, then paste `https://ntfy.sh/gharbox-k2v9x7q` into
**Settings > Your account > Phone notifications** and press **Send test**. To keep everything
inside your home, you can run your own ntfy server instead (it's open source).

## Using it away from home

Follow [docs/REMOTE_ACCESS.md](docs/REMOTE_ACCESS.md). In short: the full app stays private and is
reached through Tailscale (free, encrypted, works behind CGNAT, no router changes), and only share
links get a public address. `docker compose --profile remote up -d` starts it.

## Developing

```powershell
# server (Python 3.12+)
cd server
python -m venv .venv; .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest                                   # 35 API tests
uvicorn app.main:app --reload --port 8000   # SQLite + in-process jobs, no Docker needed

# web (Node 20+), in a second terminal
cd web
npm install
npm run dev                              # http://localhost:5173, proxies /api to :8000
```

Without `GHARBOX_DATABASE_URL` and `GHARBOX_REDIS_URL`, the server uses SQLite in `server/data`
and runs background jobs inside the API process, which is handy for development. You need
`ffmpeg` on your PATH for video thumbnails (`winget install ffmpeg`).

API docs are at http://localhost:8000/docs while the server runs.

## Testing

GharBox is tested at three levels:

| What | Where | Run |
|---|---|---|
| API tests (pytest, 68 tests) | `server/tests` | `cd server; pytest` |
| End-to-end tests in a real browser (Playwright) | `e2e/tests` | see below |
| Load test (Locust) | `loadtest/locustfile.py` | see the file's header |

End-to-end tests run against a running GharBox. On a fresh install they create the admin
account themselves; on yours, pass your admin login:

```powershell
cd e2e
npm install
npx playwright install chromium
$env:E2E_BASE_URL="http://localhost:8080"; $env:E2E_ADMIN="mahbub"; $env:E2E_PASSWORD="..."
npx playwright test          # npx playwright show-report for the HTML report
```

They cover folders and trash, version history, password-protected links opened by a visitor,
albums shared with a family member, two-factor sign-in with recovery codes, the Watch pages, the
phone layout, and the player: converting a film the browser can't play, skip intro, switching audio
and subtitles, offline copies and the next-episode countdown. The player tests need real Google
Chrome (`npx playwright install chrome`), because the open-source Chromium can't decode H.264; they
skip themselves otherwise. They create their own uniquely named test data, so they're safe to run against
your real server, though the test users and folders stay afterwards.

GitHub Actions (`.github/workflows/ci.yml`) runs the API tests, builds the web app and the Docker
images, then starts the full stack with Postgres, Redis and sample media
(`scripts/make-sample-media.sh`) and runs the Playwright suite on every push.

## License

AGPL-3.0, so GharBox stays free: anyone who runs a modified version as a service must share
their changes.
