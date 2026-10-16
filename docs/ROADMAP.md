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

## Milestone 2: play anything
- FFmpeg transcoding to HLS, with NVIDIA NVENC when available
- Subtitles (embedded and .srt), audio track choice
- Offline: download a smaller copy of a movie to watch without internet

## Milestone 3: together
- Watch parties: rooms, invite links, synced play/pause/seek over WebSocket, chat
- Shared albums, share links with expiry and password

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
