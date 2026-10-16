# Roadmap

## Milestone 1: core (this release)
- Docker stack: web (Caddy), api, worker, Postgres with pgvector, Redis
- Accounts, first-run setup, admin user management, quotas
- Resumable chunked uploads with SHA-256 de-duplication
- Files: folders, rename/move, download with resume, 30-day trash
- Photos: EXIF dates, thumbnails (JPEG, PNG, HEIC, video), timeline
- Movies: library scan, name/year parsing, ffprobe metadata, posters (TMDB optional),
  direct play with seeking, resume position, continue watching
- Phone app: camera roll backup with dedup, Live Photos, resume

## Milestone 2: play anything
- FFmpeg transcoding to HLS, with NVIDIA NVENC when available
- Subtitles (embedded and .srt), audio track choice
- TV series libraries (seasons and episodes)
- Offline downloads to phone

## Milestone 3: together
- Watch parties: rooms, invite links, synced play/pause/seek over WebSocket, chat
- Shared albums, share links with expiry and password
- Background backup on Android and iOS

## Milestone 4: local AI (docker compose --profile ai)
- Search photos by description (CLIP embeddings in pgvector)
- Face grouping, duplicate and blurry photo cleanup
- OCR for documents and screenshots
- Whisper subtitles for movies without them
- Ask in plain language through a local LLM in Ollama

## Platform
- Alembic database migrations (needed before the first schema change after release)
- 2FA and passkeys, audit log
- Bangla interface
- Admin dashboard: active streams and job queue
