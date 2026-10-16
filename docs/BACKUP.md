# Offsite backup

GharBox keeps your photos and files on one PC. A broken disk, theft, a flood or a fire would take
them with it. **Offsite backup** keeps an encrypted copy somewhere else and brings it all back
when you need it.

It uses [restic](https://restic.net) (free and open source). restic encrypts everything on your PC
before it is written, so whoever stores the copy (a cloud company, a friend) only sees scrambled
data. It also only sends what changed, so after the first run a daily backup is quick.

## What is backed up

- Photos, videos and documents (with their older versions)
- The vault (it's already encrypted with your vault passphrase; restic encrypts it again)
- A copy of the database: accounts, albums, shares, watch progress, playlists, reading positions
- Optional: the movie, music and book folders. They are large and you can usually get them again,
  so they are off by default

Thumbnails, posters and other things GharBox can rebuild are left out.

## Turn it on

**Settings > Server > Offsite backup**, choose where, press **Turn on offsite backup**.

GharBox shows a **backup password** once. **Write it down and keep it away from this PC** (with
your passport, or in a password manager). If the PC is lost, the backup can't be opened without it.
You can see it again later with **Show password** while GharBox still runs.

It backs up every day at the hour you pick, retries an hour after a failure, checks once a week
that the copy can be read back, keeps 7 daily, 5 weekly and 12 monthly copies, and notifies the
admins if something goes wrong. **Settings > Server > Security check** warns when the last good
backup is more than 3 days old.

### Where to keep it

| Choice | Good for | What to enter |
|---|---|---|
| USB or second disk | Fast, free, no internet | `/backup-disk/gharbox`, after mounting the disk (below) |
| S3-compatible storage | Real offsite copy; Backblaze B2 and Cloudflare R2 have 10 GB free | Endpoint and bucket, for example `https://s3.us-west-004.backblazeb2.com/my-gharbox`, plus an access key |
| Another computer (SFTP) | A relative's PC or a small server | `user@host:/path`, with an SSH key |
| Google Drive, OneDrive, Dropbox (rclone) | Space you already have | `remote:folder`, after connecting the account once |

The best protection is two of these: a USB disk for quick restores and a cloud bucket for disasters.

**USB or second disk.** In `docker-compose.yml`, under `x-server-volumes`, uncomment and edit:

```yaml
  - F:/GharBox Backup:/backup-disk
```

then `docker compose up -d`. A disk that stays plugged into the same PC protects against a broken
drive, not against theft or fire.

**SFTP.** Create a key and give the other computer its public half:

```bash
docker compose exec worker ssh-keygen -t ed25519 -f /data/.ssh/id_ed25519 -N ""
docker compose exec worker cat /data/.ssh/id_ed25519.pub   # add this to ~/.ssh/authorized_keys there
docker compose exec worker ssh -i /data/.ssh/id_ed25519 user@host exit   # accept the host key once
```

**Google Drive and friends (rclone).** Connect the account once (choose "No" for auto config and
follow the link it prints):

```bash
docker compose exec worker rclone config --config /data/rclone.conf
```

Name the remote, for example `gdrive`, then enter `gdrive:GharBox` in Settings.

## Restore

### A few files

Pick the copy and restore it into the data folder's `restore` folder:

```bash
docker compose exec worker sh -c 'restic snapshots'                      # list the copies
docker compose exec worker sh -c 'restic restore latest --target /data/restore --include "*/storage/mahbub/Photos/2024*"'
```

The commands need the backup's address and password. Inside the worker they are already set when
you add them to the command line:

```bash
docker compose exec -e RESTIC_REPOSITORY=/backup-disk/gharbox -e RESTIC_PASSWORD='your-backup-password' worker restic snapshots
```

Then move what you need from `gharbox-data/restore` back into place and press
**Settings > Server > Find new folders** (or upload the files again in Files).

### Everything, on a new PC

1. Install Docker Desktop and GharBox as in the README, with the same `.env` (or a new one with the
   same `POSTGRES_PASSWORD`). Mount the backup disk, or have the cloud keys ready. Don't sign in yet.
2. Start only the database and the worker:
   `docker compose up -d postgres redis worker`
3. Restore the data folder:
   ```bash
   docker compose exec -e RESTIC_REPOSITORY=<address> -e RESTIC_PASSWORD='<backup password>' worker \
     restic restore latest --target /
   ```
   (for S3 also pass `-e AWS_ACCESS_KEY_ID=... -e AWS_SECRET_ACCESS_KEY=...`)
4. Put the database back:
   ```bash
   docker compose exec worker sh -c 'pg_restore --clean --if-exists --no-owner \
     -h postgres -U gharbox -d gharbox /data/backup-staging/gharbox.pgdump'
   ```
   It asks for `POSTGRES_PASSWORD`.
5. `docker compose up -d`, sign in as before. Photos, files, albums, the vault and everyone's
   accounts are back. Turn on offsite backup again in Settings with the **same address and the
   backup password** (under "Use a backup made before").

Try a restore once, into `/data/restore`, before you need it for real.
