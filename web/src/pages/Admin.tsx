import { useCallback, useEffect, useState, type FormEvent } from "react";
import { RefreshCw, Trash2 } from "lucide-react";
import { api, ApiError, formatBytes, type Library, type Stats, type User } from "../api";
import { useAuth } from "../App";

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : "never");

export default function AdminPage() {
  const { user } = useAuth();
  return (
    <div className="page settings">
      <header className="page-head"><h1>Settings</h1></header>
      {user.is_admin && <><StatsPanel /><Libraries /><Users /></>}
      <Password />
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
      <h2>Server</h2>
      <div className="disk" role="img" aria-label={`Disk ${Math.round((used / s.disk_total) * 100)}% full`}>
        <span style={{ width: `${(used / s.disk_total) * 100}%` }} />
      </div>
      <p>{formatBytes(s.disk_free)} free of {formatBytes(s.disk_total)}. Backups use {formatBytes(s.asset_bytes)}.</p>
      <dl className="facts">
        <div><dt>Photos</dt><dd>{s.photos}</dd></div>
        <div><dt>Videos</dt><dd>{s.videos}</dd></div>
        <div><dt>Documents</dt><dd>{s.documents}</dd></div>
        <div><dt>Movies</dt><dd>{s.media_items}</dd></div>
        <div><dt>People</dt><dd>{s.users}</dd></div>
        <div><dt>Background jobs</dt><dd>{s.jobs_mode}</dd></div>
      </dl>
    </section>
  );
}

function Libraries() {
  const [libs, setLibs] = useState<Library[]>([]);
  const [name, setName] = useState("Movies");
  const [path, setPath] = useState("/media/movies");
  const [msg, setMsg] = useState("");
  const refresh = useCallback(() => { api.libraries().then(setLibs).catch(() => undefined); }, []);
  useEffect(refresh, [refresh]);

  const add = async (e: FormEvent) => {
    e.preventDefault();
    try { await api.addLibrary(name, path); setMsg("Library added. Scanning has started."); refresh(); }
    catch (err) { setMsg(err instanceof ApiError ? err.message : "Couldn't add the library"); }
  };
  return (
    <section className="panel">
      <h2>Movie folders</h2>
      {libs.length > 0 && (
        <ul className="rows">
          {libs.map((l) => (
            <li key={l.id}>
              <div><strong>{l.name}</strong> <code>{l.path}</code><br />
                <span className="muted">{l.item_count} titles, last scanned {when(l.last_scan_at)}</span></div>
              <button className="icon" title="Scan now" aria-label={`Scan ${l.name}`}
                onClick={() => api.scanLibrary(l.id).then(() => setMsg(`Scanning ${l.name}. New titles appear in a minute.`))}><RefreshCw size={16} /></button>
              <button className="icon" title="Remove (files are not deleted)" aria-label={`Remove ${l.name}`}
                onClick={() => confirm(`Remove "${l.name}" from GharBox? Your movie files stay where they are.`) && api.removeLibrary(l.id).then(refresh)}><Trash2 size={16} /></button>
            </li>
          ))}
        </ul>
      )}
      <form className="inline-form" onSubmit={add}>
        <label>Name<input value={name} onChange={(e) => setName(e.target.value)} required /></label>
        <label>Folder inside the server<input value={path} onChange={(e) => setPath(e.target.value)} required /></label>
        <button>Add folder</button>
      </form>
      <p className="muted small">With Docker, a folder on your PC must be mounted first. MOVIES_PATH in .env appears here as /media/movies.</p>
      {msg && <p role="status">{msg}</p>}
    </section>
  );
}

function Users() {
  const { user: me } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);
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
            <div><strong>{u.username}</strong> {u.is_admin && <span className="tag">admin</span>}</div>
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
    </section>
  );
}

function Password() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [msg, setMsg] = useState("");
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (next.length < 8) { setMsg("Use at least 8 characters for the new password."); return; }
    try { await api.changePassword(current, next); setMsg("Password changed."); setCurrent(""); setNext(""); }
    catch (err) { setMsg(err instanceof ApiError ? err.message : "Couldn't change the password"); }
  };
  return (
    <section className="panel">
      <h2>Your password</h2>
      <form className="inline-form" onSubmit={submit}>
        <label>Current password<input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} required autoComplete="current-password" /></label>
        <label>New password<input type="password" value={next} onChange={(e) => setNext(e.target.value)} required autoComplete="new-password" /></label>
        <button>Change password</button>
      </form>
      {msg && <p role="status">{msg}</p>}
    </section>
  );
}
