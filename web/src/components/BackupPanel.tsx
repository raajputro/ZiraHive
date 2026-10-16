import { useCallback, useEffect, useState, type FormEvent } from "react";
import { CloudUpload, HardDrive, KeyRound, ShieldCheck } from "lucide-react";
import { api, ApiError, formatBytes, type BackupInfo } from "../api";
import { digits, locale, t as tr } from "../i18n";

type Where = "disk" | "s3" | "sftp" | "rclone" | "other";
const when = new Intl.DateTimeFormat(locale(), { dateStyle: "medium", timeStyle: "short" });
const offsetHours = Math.round(-new Date().getTimezoneOffset() / 60);
const toUtc = (local: number) => (((local - offsetHours) % 24) + 24) % 24;
const toLocal = (utc: number) => (((utc + offsetHours) % 24) + 24) % 24;

function guessWhere(repo: string | null): Where {
  if (!repo || repo.startsWith("/")) return "disk";
  const scheme = repo.split(":")[0];
  return scheme === "s3" ? "s3" : scheme === "sftp" ? "sftp" : scheme === "rclone" ? "rclone" : "other";
}

/** Settings > Server > Offsite backup. */
export default function BackupPanel() {
  const [info, setInfo] = useState<BackupInfo | null>(null);
  const [editing, setEditing] = useState(false);
  const [shown, setShown] = useState<string | null>(null);
  const [msg, setMsg] = useState("");
  const [snaps, setSnaps] = useState<{ id: string; time: string }[] | null>(null);
  const load = useCallback(() => api.backup().then(setInfo).catch(() => undefined), []);
  useEffect(() => { void load(); }, [load]);
  const running = info?.runs.some((r) => r.status === "running");
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => void load(), 4000);
    return () => clearInterval(t);
  }, [running, load]);

  if (!info) return null;
  const last = info.runs.find((r) => r.kind === "backup");
  const act = async (fn: () => Promise<void>, done: string) => {
    setMsg("");
    try { await fn(); setMsg(done); setTimeout(() => void load(), 600); }
    catch (e) { setMsg(e instanceof ApiError ? e.message : tr("That didn't work")); }
  };

  return (
    <section className="panel wide-panel backup-panel">
      <h2><CloudUpload size={20} aria-hidden /> {tr("Offsite backup")}</h2>
      <p className="muted">{tr("A copy of everything that can't be replaced (photos, files, the vault and the database) on another disk or in the cloud, encrypted on this PC first, so whoever keeps it can't look inside. If this PC breaks or is stolen, you can bring it all back.")}</p>
      {!info.restic && <p className="error">{tr("restic isn't installed here. The GharBox Docker image includes it.")}</p>}

      {shown && (
        <div className="notice backup-password" role="alert">
          <strong><KeyRound size={16} aria-hidden /> {tr("Write down the backup password")}</strong>
          <p>{tr("You need it to restore on a new PC if this one is gone. Keep it with your important papers, or in a password manager.")}</p>
          <code>{shown}</code>
          <button onClick={() => setShown(null)}>{tr("I've written it down")}</button>
        </div>
      )}

      {(!info.configured || editing) ? (
        <BackupForm info={info} onSaved={(r) => { setEditing(false); setInfo(r); if (r.password) setShown(r.password); }}
          onCancel={info.configured ? () => setEditing(false) : undefined} />
      ) : (
        <>
          <dl className="backup-facts">
            <dt>{tr("Where")}</dt><dd><code>{info.repository}</code></dd>
            <dt>{tr("When")}</dt><dd>{info.enabled ? tr("Every day at {time}", { time: digits(`${String(toLocal(info.hour)).padStart(2, "0")}:00`) }) : tr("Paused")}</dd>
            <dt>{tr("What")}</dt><dd>{info.include_media ? tr("Photos, files, vault, database, and the movie and music folders") : tr("Photos, files, vault and database")}</dd>
            <dt>{tr("Last backup")}</dt>
            <dd className={last?.status === "failed" ? "error" : ""}>
              {!last ? tr("Not yet") : last.status === "running" ? tr("Running now…")
                : last.status === "failed" ? tr("Failed {date}: {message}", { date: when.format(new Date(last.started_at)), message: last.message ?? "" })
                : tr("{date}, {size} new", { date: when.format(new Date(last.finished_at ?? last.started_at)), size: formatBytes(last.bytes_added ?? 0) })}
            </dd>
          </dl>
          <div className="admin-row">
            <button className="primary" disabled={running} onClick={() => void act(api.backupNow, tr("Backup started. It runs in the background."))}>
              <HardDrive size={16} /> {tr("Back up now")}</button>
            <button disabled={running} onClick={() => void act(api.checkBackup, tr("Checking. This reads back part of the backup to make sure it can be restored."))}>
              <ShieldCheck size={16} /> {tr("Check the backup")}</button>
            <button onClick={() => void api.backupSnapshots().then(setSnaps).catch((e) => setMsg(e.message))}>{tr("Show saved copies")}</button>
            <button onClick={() => void api.backupPassword().then((p) => setShown(p.password))}><KeyRound size={16} /> {tr("Show password")}</button>
            <button onClick={() => setEditing(true)}>{tr("Change")}</button>
          </div>
          {msg && <p role="status">{msg}</p>}
          {snaps && (
            <p className="muted small">{snaps.length ? tr("{n} saved copies, newest {date}. Restoring is explained in docs/BACKUP.md.", { n: snaps.length, date: when.format(new Date(snaps[0].time)) }) : tr("No saved copies yet.")}</p>
          )}
          {info.runs.length > 0 && (
            <table className="runs">
              <thead><tr><th>{tr("When")}</th><th>{tr("What")}</th><th>{tr("Result")}</th></tr></thead>
              <tbody>
                {info.runs.map((r) => (
                  <tr key={r.id} className={r.status === "failed" ? "warn" : ""}>
                    <td className="nowrap">{when.format(new Date(r.started_at))}</td>
                    <td>{r.kind === "check" ? tr("Check") : tr("Backup")}</td>
                    <td>{r.status === "running" ? tr("Running…") : r.status === "failed" ? (r.message ?? tr("Failed"))
                      : r.kind === "check" ? tr("Readable") : tr("{n} new or changed files, {size} added", { n: (r.files_new ?? 0) + (r.files_changed ?? 0), size: formatBytes(r.bytes_added ?? 0) })}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </section>
  );
}

function BackupForm({ info, onSaved, onCancel }: { info: BackupInfo; onSaved: (r: BackupInfo) => void; onCancel?: () => void }) {
  const [where, setWhere] = useState<Where>(guessWhere(info.repository));
  const repo = info.repository ?? "";
  const [disk, setDisk] = useState(where === "disk" && repo ? repo : "/backup-disk/gharbox");
  const [endpoint, setEndpoint] = useState(where === "s3" ? repo.slice(3) : "");
  const [keyId, setKeyId] = useState("");
  const [secret, setSecret] = useState("");
  const [sftp, setSftp] = useState(where === "sftp" ? repo.slice(5) : "");
  const [remote, setRemote] = useState(where === "rclone" ? repo.slice(7) : "gdrive:GharBox");
  const [other, setOther] = useState(where === "other" ? repo : "");
  const [hour, setHour] = useState(info.configured ? toLocal(info.hour) : 2);
  const [media, setMedia] = useState(info.include_media);
  const [enabled, setEnabled] = useState(info.configured ? info.enabled : true);
  const [ownPassword, setOwnPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    const repository = where === "disk" ? disk : where === "s3" ? `s3:${endpoint.replace(/\/$/, "")}` : where === "sftp" ? `sftp:${sftp}`
      : where === "rclone" ? `rclone:${remote}` : other;
    if (where === "s3" && !!keyId !== !!secret) { setError(tr("Enter both keys, or leave both empty to keep the saved ones.")); return; }
    let env: Record<string, string> | undefined = {};
    if (where === "s3") env = keyId ? { AWS_ACCESS_KEY_ID: keyId, AWS_SECRET_ACCESS_KEY: secret } : undefined;
    setBusy(true);
    try {
      onSaved(await api.saveBackup({ repository: repository.trim(), env, hour: toUtc(hour), include_media: media, enabled,
        password: ownPassword || undefined }));
    } catch (err) { setError(err instanceof ApiError ? err.message : tr("Couldn't save")); }
    finally { setBusy(false); }
  };

  return (
    <form className="stack-form backup-form" onSubmit={submit}>
      <label>{tr("Where to keep it")}
        <select value={where} onChange={(e) => setWhere(e.target.value as Where)}>
          <option value="disk">{tr("A USB or second disk")}</option>
          <option value="s3">{tr("S3-compatible storage (Backblaze B2, Cloudflare R2, Wasabi, MinIO)")}</option>
          <option value="sftp">{tr("Another computer over SFTP")}</option>
          <option value="rclone">{tr("Google Drive, OneDrive, Dropbox and others (rclone)")}</option>
          <option value="other">{tr("Another restic address")}</option>
        </select>
      </label>
      {where === "disk" && <>
        <label>{tr("Folder")}<input value={disk} onChange={(e) => setDisk(e.target.value)} required /></label>
        <p className="muted small">{tr("Mount the disk in docker-compose.yml first (there's an example for /backup-disk). A disk that stays plugged into the same PC protects against a broken drive, not against theft or fire: take it elsewhere now and then, or use the cloud too.")}</p>
      </>}
      {where === "s3" && <>
        <label>{tr("Endpoint and bucket")}<input value={endpoint} onChange={(e) => setEndpoint(e.target.value)} required
          placeholder="https://s3.us-west-004.backblazeb2.com/my-gharbox-backup" /></label>
        <label>{tr("Access key ID")}<input value={keyId} onChange={(e) => setKeyId(e.target.value)} autoComplete="off"
          placeholder={info.env_keys.includes("AWS_ACCESS_KEY_ID") ? tr("Saved. Leave empty to keep it") : ""} /></label>
        <label>{tr("Secret access key")}<input type="password" value={secret} onChange={(e) => setSecret(e.target.value)} autoComplete="off"
          placeholder={info.env_keys.includes("AWS_SECRET_ACCESS_KEY") ? tr("Saved. Leave empty to keep it") : ""} /></label>
        <p className="muted small">{tr("Backblaze B2 and Cloudflare R2 give 10 GB free. Make a private bucket and a key that can only use that bucket.")}</p>
      </>}
      {where === "sftp" && <>
        <label>{tr("Address")}<input value={sftp} onChange={(e) => setSftp(e.target.value)} required placeholder="mahbub@192.168.0.20:/backups/gharbox" /></label>
        <p className="muted small">{tr("Signs in with an SSH key: put it in the data folder as .ssh/id_ed25519. See docs/BACKUP.md.")}</p>
      </>}
      {where === "rclone" && <>
        <label>{tr("rclone remote and folder")}<input value={remote} onChange={(e) => setRemote(e.target.value)} required /></label>
        <p className="muted small">{tr("Connect the account once with: docker compose exec worker rclone config --config /data/rclone.conf. See docs/BACKUP.md.")}</p>
      </>}
      {where === "other" && <label>{tr("restic repository")}<input value={other} onChange={(e) => setOther(e.target.value)} required placeholder="rest:https://..." /></label>}
      <label>{tr("Every day at")}
        <select value={hour} onChange={(e) => setHour(Number(e.target.value))}>
          {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{digits(`${String(h).padStart(2, "0")}:00`)}</option>)}
        </select>
      </label>
      <label className="check"><input type="checkbox" checked={media} onChange={(e) => setMedia(e.target.checked)} />
        {tr("Also back up the movie, music and book folders (they can be large)")}</label>
      {info.configured && <label className="check"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> {tr("Back up every day")}</label>}
      <details>
        <summary>{tr("Use a backup made before (enter its password)")}</summary>
        <label>{tr("Backup password")}<input type="password" value={ownPassword} onChange={(e) => setOwnPassword(e.target.value)} autoComplete="off" minLength={12} /></label>
      </details>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="admin-row">
        <button className="primary" disabled={busy}>{busy ? tr("Connecting…") : info.configured ? tr("Save") : tr("Turn on offsite backup")}</button>
        {onCancel && <button type="button" onClick={onCancel}>{tr("Cancel")}</button>}
      </div>
    </form>
  );
}
