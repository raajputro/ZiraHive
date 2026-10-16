# Roadmap

## Milestone 1: core (this release)
- Docker stack: web (Caddy), api, worker, Postgres with pgvector, Redis
- Accounts, first-run setup, admin user management, quotas
- Resumable chunked uploads with SHA-256 de-duplication
- Files: folders, rename/move, download with resume, 30-day trash
- Photos: EXIF dates, thumbnails (JPEG, PNG, HEIC, video), timeline
- Movies: library scan, name/year parsing, ffprobe metadata, posters (TMDB optional),
  direct play with seeking, resume position, continue watching
- Watch categories: one per folder (auto-discovered), movies / series / mixed types, ordering
- Web series: seasons and episodes, series pages, next episode autoplay, up next
- Browser upload from phones with dedup and resume; installable to the home screen

## Batch 1: accounts and sharing (done)
- Share links for files, folders and albums: password, expiry, view-only, visit count
- Document version history (last 20) with restore; copies allowed across folders
- Albums shared with family members, who can add their own photos
- On this day memories; screen-sized previews (HEIC in any browser); low-data mode
- Roles and storage limits editable by the admin, password reset, 2FA reset
- Two-factor sign-in (TOTP) with recovery codes; sign out everywhere; login throttling
- Audit log; notifications in-app and via ntfy (backups, albums, new videos, disk 90% full)
- Admin dashboard: active streams, job queue, disks
- Playwright end-to-end suite, Locust load test, GitHub Actions CI with Docker build

## Batch 2: play anything (done)
- On-the-fly HLS conversion with on-demand segments, seeking anywhere, pause when ahead, idle stop
- NVIDIA NVENC when available, CPU otherwise; limit on simultaneous conversions; shown on the dashboard
- Quality choice 1080p to 360p, low-data default; audio track choice; text subtitles (embedded and sidecar)
- Offline copies (MP4) with progress and notification, auto-cleanup
- Skip intro and next-episode countdown from chapters or per-series markers
- Age limits per profile; ratings from TMDB certificates, per title and per category

## Batch 3: watch parties (done)
- Start now or schedule; invite accounts; RSVP; reminder 10 minutes before and a "started" notice
- Synced play, pause and seek over a WebSocket: shared start time, clock offset from ping/pong,
  gentle speed-up or slow-down for small drift, a jump for large drift
- Wait for everyone: pauses while someone's video is loading, carries on when it's ready
- Host or everyone in control; next episode for everyone; end the party
- Chat that stays with the party, floating emoji reactions, who is here and who is loading
- Each viewer keeps their own quality, audio and subtitles; age limits apply to every guest
- Two-browser Playwright test with a WebM sample that open-source Chromium can play

## Batch 4: listen and read (done)
- New category types: Music, Audiobooks, Books (EPUB, PDF) and Comics (CBZ, CBR, CB7, CBT, page folders)
- Music: albums from tags or folders, embedded or folder cover art, artists, songs, favourites, play
  counts, Recently played, Most played, playlists with ordering
- One player for the whole app: queue, shuffle, repeat, sleep timer, Media Session (lock screen, headsets)
- Audiobooks: single files with chapters (M4B) or folders of parts, speed 0.75× to 2×, position saved
  across devices, Continue listening
- Unplayable audio (WMA, ALAC, APE, AIFF) converted once to MP3; automatic fallback when a browser fails
- Ebooks: EPUB with epub.js (themes, text size, font, contents, exact position), PDF with pdf.js
- Comics: server-scaled cached pages, ComicInfo.xml, series from names, right-to-left manga, webtoon scroll
- Age limits per category; continue reading; next in series
- The end-to-end tests send the production Content-Security-Policy, so anything it would block fails the tests

## Batch 5: private and safe (done)
- Vault: end-to-end encrypted in the browser (Web Crypto: PBKDF2-SHA256 600k, AES-256-GCM, per-file
  keys, authenticated chunks), encrypted names and thumbnails, recovery key, passphrase change,
  auto-lock, resumable encrypted uploads; the server and admins only ever hold ciphertext
- Offsite backup with restic: disk, S3-compatible, SFTP or rclone targets; database dump in every
  snapshot; daily schedule, retries, weekly read-back check, retention, failure notifications,
  security-check status, restore guide
- Bangla interface: every screen, server messages and notifications, Bangla digits and dates,
  per-account language; CI fails if a text has no Bangla
- GharBox Sync for Windows: two-way folder sync with a three-way comparison, keep-both on conflicts,
  Recycle Bin and GharBox trash for deletions, unplugged-drive and mass-delete guards, tray app,
  device sign-in, single .exe built in CI
- React Router 7 (security fix)

## Batch 6: paper and TVs (done)
- Categories use folders where they already are: drives mounted read-only, a folder browser in
  Settings, the data folder protected from being added or walked
- Words inside files: PDF text layers, Word/PowerPoint/OpenDocument, text files; Tesseract OCR
  (Bangla + English) for scanned PDFs and photos of pages; nightly catch-up; search with highlighted snippets
- Document scanner in the browser: page detection, perspective correction, filters (adaptive
  black and white), multi-page with reordering; saved as a searchable PDF made by Tesseract
- Chromecast: Cast to TV from the player with the Cast SDK loaded only on demand, direct play or
  converted HLS, subtitles, remote controls, progress saved; one-title links (12 h) accepted only on
  that title's media URLs; CORS only for those
- DLNA/UPnP media server in GharBox Sync (SSDP discovery, ContentDirectory, ConnectionManager):
  categories, series by season, Continue watching, music albums; TVs stream the original files
  with byte-range seeking; `gharbox-sync tv` for other computers
- setup.ps1 for first-time Windows setup (drives, data folder, home-network address)

## Later for playback
- Remux instead of re-encode when only the audio needs converting
- Picture-based subtitles (PGS) burned in; automatic intro detection by audio fingerprint
- Converted streams for DLNA TVs that can't play a file

## Batch 7
- Passkeys, plugins, linking two GharBox servers; voice chat in watch parties

## Milestone 4: local AI (docker compose --profile ai)
- Search photos by description (CLIP embeddings in pgvector)
- Face grouping, duplicate and blurry photo cleanup
- Whisper subtitles for movies without them
- Ask in plain language through a local LLM in Ollama

## Remote access (done)
- Private app over Tailscale, public share-links-only site via Funnel, server-side gateway guard
- Security headers and CSP, secure cookies, URL tokens limited to video links, per-address throttle
- Security check panel for the admin

## Platform
- Alembic database migrations (needed before the first schema change after release)
- Passkeys
- Admin dashboard: active streams and job queue
