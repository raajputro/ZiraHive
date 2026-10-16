# GharBox

Your own Google Drive + Jellyfin, running on your PC. Free, open source, and private: your
photos, documents and movies never leave your home.

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
  "next episode". Streams with seeking and remembers where each person stopped
- **Family**: several accounts with their own private space, admin and member roles, and
  storage limits
- **Security**: two-factor sign-in with recovery codes, "sign out everywhere", password changes
  end other sessions, slowed-down password guessing, and an activity log for the admin
- **Notifications**: a bell in the app for backups, shared albums, new movies and a nearly full
  disk, and on your phone through the free ntfy app
- **Admin dashboard**: who is watching what, background jobs, and free space on every disk

> Status: milestone 1 plus batch 1. Next up: transcoding (play any format in the browser), offline
> downloads and skip intro. See [docs/ROADMAP.md](docs/ROADMAP.md).

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

## Phone app

The backup app lives in [mobile/](mobile/README.md) (Flutter, Android and iPhone). Until it's
installed, you can upload from your phone's browser at the address from step 4.

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
```

GharBox finds new folders on start, every night, and when you press **Find new folders** in
Settings. Folder names like `english_movies` are tidied to "English Movies". Each category has a
type, guessed from its name and changeable in Settings:

| Type | Use for | How files are read |
|---|---|---|
| Movies | English, Hindi, Bangla movies | every file is a movie |
| Series | Web Series, TV Shows, Natok | every file is an episode, grouped by the show's folder |
| Movies and series | Animation, Kids | files named like `S01E02` are episodes, the rest are movies |

Episodes are recognised from `S01E02`, `1x02`, `E03`, `Episode 7` or a leading number
(`01 - Pilot.mkv`), with the season taken from the name or a `Season 2` / `Book 2` folder.
When an episode ends, the next one starts by itself, and Continue watching shows the next
episode of every series you're following.

A category on another drive: mount it in `docker-compose.yml` (there's a commented example
under the `api` volumes), restart, then use **Add a folder from another drive** in Settings.

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

## Watching from outside your home

Don't open ports to the internet. Use a free VPN that you host yourself:
**WireGuard** (or **Headscale**, the open-source Tailscale server). Your phone connects to your
home network and GharBox works as if you were on Wi-Fi.

If you do want a public HTTPS address, get a free name from DuckDNS, set
`GHARBOX_SITE_ADDRESS=yourname.duckdns.org`, forward ports 80 and 443 to this PC and map them in
`docker-compose.yml`. Caddy fetches a free Let's Encrypt certificate automatically. Note that
many ISPs in Bangladesh use CGNAT, which blocks incoming connections; the VPN route avoids that.

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
| API tests (pytest, 53 tests) | `server/tests` | `cd server; pytest` |
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
albums shared with a family member, two-factor sign-in with recovery codes, the Watch pages and
the phone layout. They create their own uniquely named test data, so they're safe to run against
your real server, though the test users and folders stay afterwards.

GitHub Actions (`.github/workflows/ci.yml`) runs the API tests, builds the web app and the Docker
images, then starts the full stack with Postgres, Redis and sample media
(`scripts/make-sample-media.sh`) and runs the Playwright suite on every push.

## License

AGPL-3.0, so GharBox stays free: anyone who runs a modified version as a service must share
their changes.
