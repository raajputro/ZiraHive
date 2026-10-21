// The Android app: download it (everyone), its phone settings (inside the app), and putting a new
// version on this ZiraHive so phones update themselves (admin).
import { useEffect, useRef, useState } from "react";
import { Download, Smartphone, Upload } from "lucide-react";
import { formatBytes } from "../api";
import { locale, t as tr } from "../i18n";
import { nativeApp } from "../native";

interface AppInfo { version_code: number; version_name: string; size: number; added_at: string }

export default function AndroidAppPanel({ admin }: { admin: boolean }) {
  const [info, setInfo] = useState<AppInfo | null | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const load = () => fetch("/api/app/android").then((r) => (r.ok ? r.json() : null)).then(setInfo).catch(() => setInfo(null));
  useEffect(() => { void load(); }, []);
  const app = nativeApp;
  const mine = app?.version();
  const backup = app?.backupStatus();

  const upload = async (file: File) => {
    setBusy(true); setMsg("");
    try {
      const r = await fetch("/api/admin/app/android", { method: "PUT", body: file, credentials: "same-origin" });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : r.statusText);
      setMsg(tr("Version {name} is ready. Phones with the app will offer the update.", { name: data.version_name }));
      void load();
    } catch (e) { setMsg((e as Error).message); }
    finally { setBusy(false); }
  };

  if (info === undefined || (!info && !admin && !nativeApp)) return null;
  return (
    <section className="panel">
      <h2><Smartphone size={18} aria-hidden />{" "}{tr("Android app")}</h2>
      {app && mine && (
        <>
          <p className="muted small">{tr("You're using the app, version {name}, on {device}.", { name: mine.name, device: mine.device })}</p>
          <p className="muted small">
            {backup?.enabled
              ? tr("Phone backup is on. {n} photos and videos backed up from this phone.", { n: (backup.uploaded ?? 0).toLocaleString(locale()) })
              : tr("Phone backup is off.")}
          </p>
          <div className="admin-row">
            <button className="primary" onClick={() => app.openBackupSettings()}>{tr("Phone backup settings")}</button>
            <button onClick={() => app.openAddressSettings()}>{tr("Change server address")}</button>
          </div>
        </>
      )}
      {!nativeApp && info && (
        <>
          <p className="muted small">{tr("Backs up your photos by itself, plays films in the phone's own player (also in a floating window), and lets you share files from any app to ZiraHive. Open this page on the phone to install it.")}</p>
          <a className="button primary" href="/api/app/android/apk" download><Download size={16} />{" "}{tr("Download for Android ({size})", { size: formatBytes(info.size) })}</a>
          <p className="muted small">{tr("Android asks once to allow installing apps from your browser; that's expected, the app isn't on the Play Store.")}</p>
        </>
      )}
      {admin && (
        <div className="android-admin">
          <p className="muted small">
            {info ? tr("On this ZiraHive: version {name}, added {date}.", { name: info.version_name, date: new Date(info.added_at).toLocaleDateString(locale()) })
              : tr("No app has been added yet. Add the .apk file from the ZiraHive build to let phones download and update it.")}
          </p>
          <input ref={input} type="file" accept=".apk,application/vnd.android.package-archive" hidden
            onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); e.target.value = ""; }} />
          <button disabled={busy} onClick={() => input.current?.click()}><Upload size={16} />{" "}{busy ? tr("Uploading…") : tr("Add a new version (.apk)")}</button>
        </div>
      )}
      {msg && <p role="status">{msg}</p>}
    </section>
  );
}
