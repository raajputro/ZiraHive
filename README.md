# GharBox

Your own Google Drive + Jellyfin, running on your PC. Free, open source, and private: your
photos, documents and movies never leave your home.

- **Backup**: phone camera roll and any files, with duplicate detection and resumable uploads
- **Photos**: timeline grouped by date, thumbnails for photos (including iPhone HEIC) and videos
- **Files**: folders, rename, move, download, a 30-day trash
- **Movies**: point it at your movie folder; it finds titles and years, makes posters, streams
  with seeking, and remembers where each person stopped
- **Family**: several accounts, each with their own private space and optional storage quota

> Status: milestone 1. Next up: transcoding (play any format in the browser), group watch
> parties, and local AI search. See [docs/ROADMAP.md](docs/ROADMAP.md).

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
   - `MOVIES_PATH`: your movie folder, for example `D:/Movies`

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

## Movies

- Name files like `Movie Name (2019).mkv`, or the common `Movie.Name.2019.1080p.mkv` style;
  both are recognised. Samples and trailers are skipped.
- For posters and plot summaries, add a free TMDB key as `GHARBOX_TMDB_API_KEY`. Without it,
  GharBox uses a frame from the movie as the poster.
- Browsers play MP4/WebM with H.264, VP9 or AV1. Other files (for example HEVC in MKV)
  show a copyable link you can open in VLC on your PC, phone or TV until transcoding lands.
- Libraries rescan every night at 03:00, or press the scan button in Settings.

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
pytest                                   # 20 API tests
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

## License

AGPL-3.0, so GharBox stays free: anyone who runs a modified version as a service must share
their changes.
