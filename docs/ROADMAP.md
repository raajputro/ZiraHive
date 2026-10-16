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

## Later for playback
- Remux instead of re-encode when only the audio needs converting
- Picture-based subtitles (PGS) burned in; automatic intro detection by audio fingerprint
- Chromecast and DLNA

## Batches 4 to 7
- Batch 4: music, audiobooks, ebooks and comics
- Batch 5: encrypted vault, encrypted offsite backup, Bangla interface, PC sync client
- Batch 6: document scanner and OCR in the browser, Chromecast and DLNA
- Batch 7: passkeys, plugins, linking two GharBox servers; voice chat in watch parties

## Milestone 4: local AI (docker compose --profile ai)
- Search photos by description (CLIP embeddings in pgvector)
- Face grouping, duplicate and blurry photo cleanup
- OCR for documents and screenshots
- Whisper subtitles for movies without them
- Ask in plain language through a local LLM in Ollama

## Remote access (done)
- Private app over Tailscale, public share-links-only site via Funnel, server-side gateway guard
- Security headers and CSP, secure cookies, URL tokens limited to video links, per-address throttle
- Security check panel for the admin

## Platform
- Alembic database migrations (needed before the first schema change after release)
- Passkeys
- Bangla interface
- Admin dashboard: active streams and job queue
