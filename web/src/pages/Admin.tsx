import { useCallback, useEffect, useState, type FormEvent } from "react";
import { RefreshCw, Trash2, Pencil, ArrowUp, ArrowDown, FolderSearch } from "lucide-react";
import { api, ApiError, formatBytes, type Library, type LibraryKind, type Stats, type User } from "../api";
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
