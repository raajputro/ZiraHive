import { useCallback, useEffect, useState, type FormEvent } from "react";
import { RefreshCw, Trash2, Pencil, ArrowUp, ArrowDown, FolderSearch, ShieldCheck, Bell, Smartphone, Check, AlertTriangle } from "lucide-react";
import { api, ApiError, formatBytes, AGE_LABEL, AGE_OPTIONS, type Activity, type AdminUser, type AuditEvent, type Library, type LibraryKind,
  type Me, type SecurityItem, type Stats } from "../api";
import { useAuth } from "../App";
import { usePrefs } from "../prefs";
import Dialog from "../components/Dialog";

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : "never");

type Tab = "account" | "server" | "people" | "log";

export default function AdminPage() {
  const { user } = useAuth();
  const [tab, setTab] = useState<Tab>(() => (location.hash.slice(1) as Tab) || "account");
  const go = (t: Tab) => { setTab(t); history.replaceState(null, "", `#${t}`); };
  useEffect(() => {
    const onHash = () => setTab((location.hash.slice(1) as Tab) || "account");
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const tabs: [Tab, string][] = [["account", "Your account"]];
  if (user.is_admin) tabs.push(["server", "Server"], ["people", "People"], ["log", "Activity log"]);
  return (
    <div className="page settings">
      <header className="page-head"><h1>Settings</h1></header>
      <nav className="lib-tabs settings-tabs" aria-label="Settings sections">
        {tabs.map(([t, label]) => (
          <button key={t} className={tab === t ? "active" : ""} aria-current={tab === t ? "page" : undefined} onClick={() => go(t)}>{label}</button>
        ))}
      </nav>
      {tab === "account" && <><AccountPanel /><TwoFactorPanel /><NotificationsPanel /><Password /></>}
      {tab === "server" && user.is_admin && <><SecurityPanel /><StatsPanel /><ActivityPanel /><Libraries /></>}
      {tab === "people" && user.is_admin && <Users />}
      {tab === "log" && user.is_admin && <AuditPanel />}
    </div>
  );
}

function StatsPanel() {
  const [s, setS] = useState<Stats | null>(null);
  useEffect(() => { api.stats().then(setS).catch(() => undefined); }, []);
  if (!s) return null;
  const used = s.disk_total - s.disk_free;
  return (
    <section className="panel">
      <h2>Storage</h2>
      <div className="disk" role="img" aria-label={`Disk ${Math.round((used / s.disk_total) * 100)}% full`}>
        <span style={{ width: `${(used / s.disk_total) * 100}%` }} />
      </div>
      <p>{formatBytes(s.disk_free)} free of {formatBytes(s.disk_total)}. Backups use {formatBytes(s.asset_bytes)}.</p>
      <dl className="facts">
        <div><dt>Photos</dt><dd>{s.photos}</dd></div>
        <div><dt>Videos</dt><dd>{s.videos}</dd></div>
        <div><dt>Documents</dt><dd>{s.documents}</dd></div>
        <div><dt>Movies and episodes</dt><dd>{s.media_items}</dd></div>
        <div><dt>People</dt><dd>{s.users}</dd></div>
        <div><dt>Background jobs</dt><dd>{s.jobs_mode}</dd></div>
      </dl>
    </section>
  );
}

const KIND_LABEL: Record<LibraryKind, string> = {
  movies: "Movies",
  shows: "Series",
  mixed: "Movies and series",
};

function Libraries() {
  const [libs, setLibs] = useState<Library[]>([]);
  const [name, setName] = useState("");
  const [path, setPath] = useState("");
  const [kind, setKind] = useState<LibraryKind>("movies");
  const [msg, setMsg] = useState("");
  const refresh = useCallback(() => { api.libraries().then(setLibs).catch(() => undefined); }, []);
  useEffect(refresh, [refresh]);

  const run = async (fn: () => Promise<unknown>, done?: string) => {
    try { await fn(); if (done) setMsg(done); refresh(); }
    catch (err) { setMsg(err instanceof ApiError ? err.message : "That didn't work"); }
  };
  const findFolders = () => run(async () => {
    const found = await api.discoverLibraries();
    setMsg(found.length
      ? `Added ${found.map((l) => l.name).join(", ")}. Scanning has started.`
      : "No new folders found. Each category needs its own folder inside your media folder.");
  });
  const move = (i: number, delta: number) => {
    const ids = libs.map((l) => l.id);
    const [moved] = ids.splice(i, 1);
    ids.splice(i + delta, 0, moved);
    void run(() => api.reorderLibraries(ids));
  };
  const rename = (l: Library) => {
    const next = prompt("Category name", l.name);
    if (next?.trim() && next !== l.name) void run(() => api.updateLibrary(l.id, { name: next.trim() }));
  };
  const add = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => { await api.addLibrary(name, path, kind); setName(""); setPath(""); }, "Category added. Scanning has started.");
  };

  return (
    <section className="panel">
      <h2>Watch categories</h2>
      <p className="muted small">Every folder inside your media folder becomes a category, such as English Movies, Hindi Movies,
        Bangla Movies, Web Series or Animation. They show on the Watch page in this order.</p>
      <div className="panel-actions">
        <button onClick={findFolders}><FolderSearch size={16} /> Find new folders</button>
      </div>
      {libs.length > 0 && (
        <ul className="rows">
          {libs.map((l, i) => (
            <li key={l.id}>
              <div className="order">
                <button className="icon" aria-label={`Move ${l.name} up`} disabled={i === 0} onClick={() => move(i, -1)}><ArrowUp size={15} /></button>
                <button className="icon" aria-label={`Move ${l.name} down`} disabled={i === libs.length - 1} onClick={() => move(i, 1)}><ArrowDown size={15} /></button>
              </div>
              <div>
                <strong>{l.name}</strong> <code>{l.path}</code><br />
                <span className={l.available ? "muted" : "error"}>
                  {l.available ? `${l.item_count} titles, last scanned ${when(l.last_scan_at)}` : "Folder not found. Is the drive connected?"}
                </span>
              </div>
              <label className="sr" htmlFor={`kind-${l.id}`}>Type of {l.name}</label>
              <select id={`kind-${l.id}`} value={l.kind} title="Changing the type re-sorts movies and episodes"
                onChange={(e) => void run(() => api.updateLibrary(l.id, { kind: e.target.value as LibraryKind }),
                  `${l.name} is now ${KIND_LABEL[e.target.value as LibraryKind].toLowerCase()}. Re-scanning.`)}>
                {(Object.keys(KIND_LABEL) as LibraryKind[]).map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
              </select>
              <label className="sr" htmlFor={`age-${l.id}`}>Who {l.name} suits</label>
              <select id={`age-${l.id}`} value={l.age_rating ?? ""} title="Age for titles here that have no rating of their own"
                onChange={(e) => void run(() => api.updateLibrary(l.id, { age_rating: e.target.value === "" ? -1 : Number(e.target.value) }))}>
                <option value="">Age: not set</option>
                {AGE_OPTIONS.map((a) => <option key={a} value={a}>Suits {AGE_LABEL[a]}</option>)}
              </select>
              <button className="icon" title="Rename" aria-label={`Rename ${l.name}`} onClick={() => rename(l)}><Pencil size={16} /></button>
              <button className="icon" title="Scan now" aria-label={`Scan ${l.name}`}
                onClick={() => void run(() => api.scanLibrary(l.id), `Scanning ${l.name}. New titles appear in a minute.`)}><RefreshCw size={16} /></button>
              <button className="icon" title="Remove (files are not deleted)" aria-label={`Remove ${l.name}`}
                onClick={() => confirm(`Remove "${l.name}" from GharBox? Your files stay where they are.`) && void run(() => api.removeLibrary(l.id))}><Trash2 size={16} /></button>
            </li>
          ))}
        </ul>
      )}
      <details className="add-folder">
        <summary>Add a folder from another drive</summary>
        <form className="inline-form" onSubmit={add}>
          <label>Name<input value={name} onChange={(e) => setName(e.target.value)} placeholder="Korean Dramas" required /></label>
          <label>Folder inside the server<input value={path} onChange={(e) => setPath(e.target.value)} placeholder="/media-e/korean" required /></label>
          <label>Type
            <select value={kind} onChange={(e) => setKind(e.target.value as LibraryKind)}>
              {(Object.keys(KIND_LABEL) as LibraryKind[]).map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
            </select>
          </label>
          <button>Add category</button>
        </form>
        <p className="muted small">With Docker, mount the drive in docker-compose.yml first. See the README.</p>
      </details>
      {msg && <p role="status">{msg}</p>}
    </section>
  );
}


// ------------------------------------------------------------------ account

function AccountPanel() {
  const { lowData, setLowData } = usePrefs();
  const { user } = useAuth();
  const [me, setMe] = useState<Me | null>(null);
  const [msg, setMsg] = useState("");
  useEffect(() => { api.me().then(setMe).catch(() => undefined); }, []);
  const everywhere = async () => {
    if (!confirm("Sign out on every phone and browser, including this one?")) return;
    await api.logoutAll();
    setMsg("Signed out everywhere.");
    window.dispatchEvent(new Event("gharbox:signed-out"));
  };
  const quota = me?.quota_bytes;
  return (
    <section className="panel">
      <h2>{user.username}</h2>
      {me && (
        <>
          {quota ? (
            <div className="disk" role="img" aria-label={`${Math.round((me.used_bytes / quota) * 100)}% of your space used`}>
              <span style={{ width: `${Math.min(100, (me.used_bytes / quota) * 100)}%` }} />
            </div>
          ) : null}
          <p>You're using {formatBytes(me.used_bytes)}{quota ? ` of ${formatBytes(quota)}` : ""}, including older versions of documents.</p>
        </>
      )}
      <label className="check toggle-row">
        <input type="checkbox" checked={lowData} onChange={(e) => setLowData(e.target.checked)} />
        <span><strong>Low-data mode on this device</strong><br />
          <span className="muted small">Shows small previews and doesn't start videos by itself. Good on mobile data.</span></span>
      </label>
      <button onClick={() => void everywhere()}><Smartphone size={16} /> Sign out everywhere</button>
      {msg && <p role="status">{msg}</p>}
    </section>
  );
}

function TwoFactorPanel() {
  const { user, refreshUser } = useAuth();
  const [setup, setSetup] = useState<{ secret: string; qr_svg: string } | null>(null);
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [password, setPassword] = useState("");
  const [msg, setMsg] = useState("");
  const start = async () => {
    try { setSetup(await api.twoFactorSetup()); setMsg(""); }
    catch (e) { setMsg(e instanceof ApiError ? e.message : "Couldn't start setup"); }
  };
  const enable = async (e: FormEvent) => {
    e.preventDefault();
    try { setCodes((await api.twoFactorEnable(code.trim())).recovery_codes); setSetup(null); setCode(""); refreshUser(); }
    catch (err) { setMsg(err instanceof ApiError ? err.message : "That didn't work"); }
  };
  const disable = async (e: FormEvent) => {
    e.preventDefault();
    try { await api.twoFactorDisable(password); setPassword(""); setMsg("Two-factor sign-in is off."); refreshUser(); }
    catch (err) { setMsg(err instanceof ApiError ? err.message : "That didn't work"); }
  };
  return (
    <section className="panel">
      <h2><ShieldCheck size={18} aria-hidden /> Two-factor sign-in</h2>
      {user.totp_enabled ? (
        <>
          <p>On. Signing in needs your password and a code from your authenticator app.</p>
          <form className="inline-form" onSubmit={disable}>
            <label>Password to turn it off<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="current-password" /></label>
            <button className="danger">Turn off</button>
          </form>
        </>
      ) : setup ? (
        <div className="totp-setup">
          <div className="qr" dangerouslySetInnerHTML={{ __html: setup.qr_svg }} aria-label="QR code for your authenticator app" role="img" />
          <form className="stack-form" onSubmit={enable}>
            <p>Scan this with an authenticator app such as Aegis, 2FAS or Google Authenticator. Can't scan? Type this key: <code>{setup.secret}</code></p>
            <label>6-digit code from the app<input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" autoComplete="one-time-code" required /></label>
            <button className="primary">Turn on</button>
          </form>
        </div>
      ) : (
        <>
          <p className="muted">Protects your account even if someone learns your password.</p>
          <button onClick={() => void start()}>Set up two-factor sign-in</button>
        </>
      )}
      {msg && <p role="status">{msg}</p>}
      {codes && (
        <Dialog title="Save your recovery codes" onClose={() => setCodes(null)}>
          <p>If you lose your phone, each of these codes signs you in once. Keep them somewhere safe, like a password manager or on paper.</p>
          <ul className="recovery">{codes.map((c) => <li key={c}><code>{c}</code></li>)}</ul>
          <button className="primary" onClick={() => void navigator.clipboard?.writeText(codes.join("\n"))}>Copy codes</button>
        </Dialog>
      )}
    </section>
  );
}

function NotificationsPanel() {
  const [ntfy, setNtfy] = useState("");
  const [msg, setMsg] = useState("");
  useEffect(() => { api.me().then((m) => setNtfy(m.ntfy_url ?? "")).catch(() => undefined); }, []);
  const save = async (e: FormEvent) => {
    e.preventDefault();
    try { await api.saveMySettings(ntfy.trim()); setMsg(ntfy.trim() ? "Saved. Send a test to check it." : "Phone notifications are off."); }
    catch (err) { setMsg(err instanceof ApiError ? err.message : "Couldn't save"); }
  };
  return (
    <section className="panel">
      <h2><Bell size={18} aria-hidden /> Phone notifications</h2>
      <p className="muted small">GharBox shows notifications in the bell. To also get them on your phone, install the free ntfy app,
        subscribe to a topic with a long random name, and paste its address here, for example https://ntfy.sh/gharbox-k2v9x7q.</p>
      <form className="inline-form" onSubmit={save}>
        <label>ntfy topic address<input value={ntfy} onChange={(e) => setNtfy(e.target.value)} placeholder="https://ntfy.sh/your-topic" /></label>
        <button>Save</button>
        <button type="button" onClick={() => void api.testNotification().then(() => setMsg("Test sent."))}>Send test</button>
      </form>
      {msg && <p role="status">{msg}</p>}
    </section>
  );
}

// ------------------------------------------------------------------- server

function SecurityPanel() {
  const [items, setItems] = useState<SecurityItem[] | null>(null);
  useEffect(() => { api.security().then(setItems).catch(() => undefined); }, []);
  if (!items) return null;
  const problems = items.filter((i) => !i.ok && i.level !== "info").length;
  return (
    <section className="panel">
      <h2><ShieldCheck size={18} aria-hidden /> Security check</h2>
      <p className={problems ? "error" : "muted"}>{problems ? `${problems} thing${problems === 1 ? "" : "s"} to fix` : "Everything important is in place."}</p>
      <ul className="checks">
        {items.map((i) => (
          <li key={i.title} className={i.ok ? "ok" : i.level}>
            <span className="mark" aria-hidden>{i.ok ? <Check size={15} /> : <AlertTriangle size={15} />}</span>
            <div><strong>{i.title}</strong>{i.fix && <p>{i.fix}</p>}</div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function ActivityPanel() {
  const [a, setA] = useState<Activity | null>(null);
  useEffect(() => {
    const load = () => api.activity().then(setA).catch(() => undefined);
    void load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);
  if (!a) return null;
  return (
    <section className="panel">
      <h2>Right now</h2>
      {a.streams.length === 0 ? <p className="muted">Nobody is watching anything.</p> : (
        <ul className="rows">
          {a.streams.map((s) => <li key={s.username + s.media_id}><div><strong>{s.username}</strong> is watching {s.title}</div></li>)}
        </ul>
      )}
      {a.transcodes.length > 0 && (
        <ul className="rows">
          {a.transcodes.map((t) => (
            <li key={t.title + t.quality}><div>Converting <strong>{t.title}</strong> to {t.quality} for {t.viewers.join(", ")}<br />
              <span className="muted small">{t.encoder === "h264_nvenc" ? "NVIDIA GPU" : "CPU"}{t.paused ? ", paused (far enough ahead)" : ""}{!t.running ? ", finished" : ""}</span></div></li>
          ))}
        </ul>
      )}
      <p className="muted small">Background jobs waiting: {a.jobs_queued ?? "unknown"} ({a.jobs_mode}). Thumbnail and poster cache: {formatBytes(a.cache_bytes)}.
        Running since {new Date(a.started_at).toLocaleString()}.</p>
      <h3 className="sub">Disks</h3>
      {a.disks.map((d) => {
        const used = (d.total - d.free) / d.total;
        return (
          <div key={d.path} className="disk-row">
            <span>{d.label}</span>
            <div className={`disk ${used > 0.9 ? "danger" : ""}`} role="img" aria-label={`${Math.round(used * 100)}% full`}><span style={{ width: `${used * 100}%` }} /></div>
            <span className="muted small">{formatBytes(d.free)} free of {formatBytes(d.total)}</span>
          </div>
        );
      })}
    </section>
  );
}

function AuditPanel() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [more, setMore] = useState(true);
  const load = useCallback(async (before?: string) => {
    const page = await api.audit(before);
    setEvents((e) => (before ? [...e, ...page] : page));
    setMore(page.length === 100);
  }, []);
  useEffect(() => { void load(); }, [load]);
  const label: Record<string, string> = {
    login: "Signed in", login_failed: "Wrong password", login_failed_2fa: "Wrong 2FA code", setup: "Set up GharBox",
    logout_all: "Signed out everywhere", password_changed: "Changed password", "2fa_enabled": "Turned on 2FA",
    "2fa_disabled": "Turned off 2FA", user_created: "Added a person", user_updated: "Changed a person",
    user_deleted: "Removed a person", share_created: "Made a share link", share_deleted: "Deleted a share link",
    album_shared: "Shared an album", trash_emptied: "Emptied the trash", version_restored: "Restored a version",
  };
  return (
    <section className="panel wide-panel">
      <h2>Activity log</h2>
      <table className="filelist audit">
        <thead><tr><th>When</th><th>Who</th><th>What</th><th className="hide-sm">From</th></tr></thead>
        <tbody>
          {events.map((e) => (
            <tr key={e.id} className={e.action.includes("failed") ? "warn" : ""}>
              <td className="nowrap">{new Date(e.created_at).toLocaleString()}</td>
              <td>{e.username ?? "unknown"}</td>
              <td>{label[e.action] ?? e.action}{e.detail ? `: ${e.detail}` : ""}</td>
              <td className="hide-sm muted">{e.ip}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {more && events.length > 0 && <button onClick={() => void load(events[events.length - 1].created_at)}>Show older</button>}
    </section>
  );
}

// ------------------------------------------------------------------- people

function Users() {
  const { user: me } = useAuth();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);
  const [editing, setEditing] = useState<AdminUser | null>(null);
  const [msg, setMsg] = useState("");
  const refresh = useCallback(() => { api.users().then(setUsers).catch(() => undefined); }, []);
  useEffect(refresh, [refresh]);

  const add = async (e: FormEvent) => {
    e.preventDefault();
    if (password.length < 8) { setMsg("Use at least 8 characters for the password."); return; }
    try {
      await api.createUser(username, password, isAdmin);
      setMsg(`Added ${username}. They can sign in now.`);
      setUsername(""); setPassword(""); setIsAdmin(false); refresh();
    } catch (err) { setMsg(err instanceof ApiError ? err.message : "Couldn't add the person"); }
  };
  return (
    <section className="panel">
      <h2>People</h2>
      <ul className="rows">
        {users.map((u) => (
          <li key={u.id}>
            <div>
              <strong>{u.username}</strong> {u.is_admin && <span className="tag">admin</span>} {u.totp_enabled && <span className="tag">2FA</span>}
              {u.max_age != null && <span className="tag">up to {AGE_LABEL[u.max_age]}</span>}<br />
              <span className="muted small">{formatBytes(u.used_bytes)} used{u.quota_bytes ? ` of ${formatBytes(u.quota_bytes)}` : ", no limit"}</span>
            </div>
            <button className="icon" aria-label={`Edit ${u.username}`} title="Edit" onClick={() => setEditing(u)}><Pencil size={16} /></button>
            {u.id !== me.id && (
              <button className="icon" aria-label={`Remove ${u.username}`} title="Remove account (their files stay on disk)"
                onClick={() => confirm(`Remove ${u.username}'s account? Their files stay on disk.`) && api.deleteUser(u.id).then(refresh)}><Trash2 size={16} /></button>
            )}
          </li>
        ))}
      </ul>
      <form className="inline-form" onSubmit={add}>
        <label>Username<input value={username} onChange={(e) => setUsername(e.target.value)} required pattern="[A-Za-z0-9_.\-]+" /></label>
        <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="new-password" /></label>
        <label className="check"><input type="checkbox" checked={isAdmin} onChange={(e) => setIsAdmin(e.target.checked)} /> Admin</label>
        <button>Add person</button>
      </form>
      {msg && <p role="status">{msg}</p>}
      {editing && <EditUser user={editing} isMe={editing.id === me.id} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); refresh(); }} />}
    </section>
  );
}

function EditUser({ user, isMe, onClose, onSaved }: { user: AdminUser; isMe: boolean; onClose: () => void; onSaved: () => void }) {
  const [admin, setAdmin] = useState(user.is_admin);
  const [maxAge, setMaxAge] = useState<string>(user.max_age == null ? "" : String(user.max_age));
  const [quota, setQuota] = useState(user.quota_bytes ? String(+(user.quota_bytes / 1024 ** 3).toFixed(2)) : "");
  const [newPassword, setNewPassword] = useState("");
  const [reset2fa, setReset2fa] = useState(false);
  const [error, setError] = useState("");
  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (newPassword && newPassword.length < 8) { setError("Use at least 8 characters for the password."); return; }
    try {
      await api.updateUser(user.id, {
        is_admin: admin, max_age: maxAge === "" ? -1 : Number(maxAge), ...(quota.trim() ? { quota_gb: Number(quota) } : { clear_quota: true }),
        new_password: newPassword || undefined, reset_2fa: reset2fa || undefined,
      });
      onSaved();
    } catch (err) { setError(err instanceof ApiError ? err.message : "Couldn't save"); }
  };
  return (
    <Dialog title={`Edit ${user.username}`} onClose={onClose}>
      <form className="stack-form" onSubmit={save}>
        <label className="check"><input type="checkbox" checked={admin} disabled={isMe} onChange={(e) => setAdmin(e.target.checked)} /> Admin (can manage people, categories and the server)</label>
        <label>Movies and series they can see
          <select value={maxAge} onChange={(e) => setMaxAge(e.target.value)} disabled={isMe}>
            <option value="">Everything</option>
            {AGE_OPTIONS.filter((a) => a < 18).map((a) => <option key={a} value={a}>Only rated {AGE_LABEL[a]}{a ? " or younger" : ""}</option>)}
          </select>
        </label>
        {maxAge !== "" && <p className="muted small">Titles without a rating are hidden from this profile. Give whole categories an age in Settings, Server.</p>}
        <label>Storage limit in GB<input type="number" min="0" step="any" value={quota} onChange={(e) => setQuota(e.target.value)} placeholder="No limit" /></label>
        <label>New password<input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} autoComplete="new-password" placeholder="Leave empty to keep it" /></label>
        {user.totp_enabled && (
          <label className="check"><input type="checkbox" checked={reset2fa} onChange={(e) => setReset2fa(e.target.checked)} /> Turn off two-factor sign-in (lost phone)</label>
        )}
        {error && <p className="error" role="alert">{error}</p>}
        <button className="primary">Save</button>
      </form>
    </Dialog>
  );
}

function Password() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [msg, setMsg] = useState("");
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (next.length < 8) { setMsg("Use at least 8 characters for the new password."); return; }
    try { await api.changePassword(current, next); setMsg("Password changed. Other devices need to sign in again."); setCurrent(""); setNext(""); }
    catch (err) { setMsg(err instanceof ApiError ? err.message : "Couldn't change the password"); }
  };
  return (
    <section className="panel">
      <h2>Password</h2>
      <form className="inline-form" onSubmit={submit}>
        <label>Current password<input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} required autoComplete="current-password" /></label>
        <label>New password<input type="password" value={next} onChange={(e) => setNext(e.target.value)} required autoComplete="new-password" /></label>
        <button>Change password</button>
      </form>
      {msg && <p role="status">{msg}</p>}
    </section>
  );
}
