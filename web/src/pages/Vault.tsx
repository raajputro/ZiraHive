import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Download, FileText, KeyRound, Lock, Pencil, ShieldCheck, Trash2, Upload, Film, Music } from "lucide-react";
import { api, ApiError, formatBytes, type VaultInfo, type VaultItem } from "../api";
import { t as tr, locale } from "../i18n";
import Dialog from "../components/Dialog";
import {
  CHUNK, createVault, decryptStream, encryptChunk, encryptedSize, newFileKey, open, openFileKey, openMeta, rewrap, seal,
  sealMeta, secureContextOk, unb64, unlockWithPassphrase, unlockWithRecovery, type FileKey, type FileMeta,
} from "../vault/crypto";
import { lock, masterBytes, unlock, useVaultKey } from "../vault/session";

const MIN_PASSPHRASE = 10;
const dateFmt = new Intl.DateTimeFormat(locale(), { day: "numeric", month: "short", year: "numeric" });

export default function VaultPage() {
  const key = useVaultKey();
  const [info, setInfo] = useState<VaultInfo | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => api.vault().then(setInfo).catch((e) => setError(e.message)), []);
  useEffect(() => { void load(); }, [load]);

  if (!secureContextOk()) {
    return (
      <Shell>
        <div className="empty">
          <h2>{tr("The vault needs a secure connection")}</h2>
          <p>{tr("Open ZiraHive through https (for example your Tailscale address) or on this computer as localhost. Over plain http the browser doesn't allow encryption.")}</p>
        </div>
      </Shell>
    );
  }
  if (error) return <Shell><p className="error">{error}</p></Shell>;
  if (!info) return <Shell><div aria-busy="true" /></Shell>;
  if (!info.set_up) return <Shell><SetUp onDone={load} /></Shell>;
  if (!key) return <Shell><Unlock info={info} onReset={load} /></Shell>;
  return <Shell><Contents info={info} master={key} reload={load} /></Shell>;
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="page vault-page">
      <header className="page-head"><h1><ShieldCheck size={26} aria-hidden /> {tr("Vault")}</h1></header>
      {children}
    </div>
  );
}

// ------------------------------------------------------------------ setting up

function SetUp({ onDone }: { onDone: () => void }) {
  const [pass, setPass] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [recovery, setRecovery] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const pending = useRef<{ master: CryptoKey; raw: Uint8Array } | null>(null);

  const create = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    if (pass.length < MIN_PASSPHRASE) { setError(tr("Use at least {n} characters. A short sentence works well.", { n: MIN_PASSPHRASE })); return; }
    if (pass !== again) { setError(tr("The two passphrases are different.")); return; }
    setBusy(true);
    try {
      const v = await createVault(pass);
      await api.setUpVault(v.setup);
      pending.current = { master: v.master, raw: v.masterRaw };
      setRecovery(v.recoveryText);
    } catch (err) { setError(err instanceof ApiError ? err.message : tr("Couldn't set up the vault")); }
    finally { setBusy(false); }
  };

  if (recovery) {
    const download = () => {
      const blob = new Blob([`ZiraHive vault recovery key\n\n${recovery}\n\nKeep this somewhere safe. With it you can open your vault if you forget the passphrase.\n`], { type: "text/plain" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "zirahive-vault-recovery-key.txt";
      a.click();
      URL.revokeObjectURL(a.href);
    };
    return (
      <section className="panel vault-setup">
        <h2><KeyRound size={20} aria-hidden /> {tr("Your recovery key")}</h2>
        <p>{tr("If you forget your passphrase, this key is the only other way in. Nobody else can open your vault, not even the ZiraHive admin, so nobody can reset it for you.")}</p>
        <code className="recovery-key" aria-label={tr("Recovery key")}>{recovery}</code>
        <div className="admin-row">
          <button onClick={() => void navigator.clipboard?.writeText(recovery)}>{tr("Copy")}</button>
          <button onClick={download}><Download size={16} /> {tr("Save as a file")}</button>
        </div>
        <label className="check"><input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} />
          {tr("I've saved my recovery key somewhere safe")}</label>
        <button className="primary" disabled={!saved} onClick={() => {
          const p = pending.current!;
          unlock(p.master, p.raw);
          onDone();
        }}>{tr("Open my vault")}</button>
      </section>
    );
  }

  return (
    <section className="panel vault-setup">
      <h2>{tr("A locked space for private files")}</h2>
      <p>{tr("Files in the vault are encrypted on this device before they're sent. The server only stores scrambled data: the ZiraHive admin can't open them, and neither can anyone who takes the disk.")}</p>
      <p className="muted small">{tr("Choose a passphrase you don't use anywhere else. You'll also get a recovery key to keep somewhere safe.")}</p>
      <form className="stack-form" onSubmit={create}>
        <label>{tr("Vault passphrase")}<input type="password" value={pass} onChange={(e) => setPass(e.target.value)} autoComplete="new-password" required /></label>
        <label>{tr("Type it again")}<input type="password" value={again} onChange={(e) => setAgain(e.target.value)} autoComplete="new-password" required /></label>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="primary" disabled={busy}>{busy ? tr("Setting up…") : tr("Create my vault")}</button>
      </form>
    </section>
  );
}

// ------------------------------------------------------------------ unlocking

function Unlock({ info, onReset }: { info: VaultInfo; onReset: () => void }) {
  const [mode, setMode] = useState<"pass" | "recovery" | "reset">("pass");
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [newPass, setNewPass] = useState<{ raw: Uint8Array; master: CryptoKey } | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      if (mode === "reset") {
        if (!confirm(tr("Delete everything in your vault? This can't be undone."))) return;
        await api.resetVault(value);
        onReset();
        return;
      }
      const v = { salt: info.salt!, iterations: info.iterations!, wrapped_key: info.wrapped_key!, recovery_wrapped_key: info.recovery_wrapped_key! };
      const r = mode === "pass" ? await unlockWithPassphrase(v, value) : await unlockWithRecovery(v, value);
      if (mode === "recovery") setNewPass({ raw: r.masterRaw, master: r.master });
      else unlock(r.master, r.masterRaw);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : mode === "pass" ? tr("That passphrase didn't open the vault.") : tr("That recovery key didn't open the vault."));
    } finally { setBusy(false); setValue(""); }
  };

  if (newPass) return <ChangePassphrase raw={newPass.raw} title={tr("Choose a new passphrase")} onDone={() => unlock(newPass.master, newPass.raw)} />;

  return (
    <section className="panel vault-setup">
      <h2><Lock size={20} aria-hidden /> {tr("Your vault is locked")}</h2>
      <p className="muted">{tr("{n} files, {size}", { n: info.item_count, size: formatBytes(info.bytes) })}</p>
      <form className="stack-form" onSubmit={submit}>
        {mode === "pass" && <label>{tr("Vault passphrase")}<input type="password" value={value} onChange={(e) => setValue(e.target.value)} autoComplete="current-password" required autoFocus /></label>}
        {mode === "recovery" && <label>{tr("Recovery key")}<input value={value} onChange={(e) => setValue(e.target.value)} placeholder="ABCD-EFGH-…" required autoFocus spellCheck={false} /></label>}
        {mode === "reset" && <>
          <p className="error">{tr("Without the passphrase or the recovery key nobody can open these files. You can only start over with an empty vault.")}</p>
          <label>{tr("Your ZiraHive account password")}<input type="password" value={value} onChange={(e) => setValue(e.target.value)} autoComplete="current-password" required /></label>
        </>}
        {error && <p className="error" role="alert">{error}</p>}
        <button className={mode === "reset" ? "danger" : "primary"} disabled={busy}>
          {busy ? tr("Opening…") : mode === "reset" ? tr("Empty the vault") : tr("Unlock")}</button>
      </form>
      <div className="vault-links">
        {mode !== "pass" && <button className="link-btn" onClick={() => { setMode("pass"); setError(""); }}>{tr("Use my passphrase")}</button>}
        {mode !== "recovery" && <button className="link-btn" onClick={() => { setMode("recovery"); setError(""); }}>{tr("Forgot the passphrase? Use the recovery key")}</button>}
        {mode !== "reset" && <button className="link-btn" onClick={() => { setMode("reset"); setError(""); }}>{tr("Lost both?")}</button>}
      </div>
    </section>
  );
}

function ChangePassphrase({ raw, title, onDone, onCancel }: { raw: Uint8Array; title: string; onDone: () => void; onCancel?: () => void }) {
  const [pass, setPass] = useState("");
  const [again, setAgain] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    if (pass.length < MIN_PASSPHRASE) { setError(tr("Use at least {n} characters. A short sentence works well.", { n: MIN_PASSPHRASE })); return; }
    if (pass !== again) { setError(tr("The two passphrases are different.")); return; }
    setBusy(true);
    try { await api.changeVaultKeys({ password, ...(await rewrap(raw, pass)) }); onDone(); }
    catch (err) { setError(err instanceof ApiError ? err.message : tr("Couldn't save")); }
    finally { setBusy(false); }
  };
  return (
    <section className="panel vault-setup">
      <h2>{title}</h2>
      <form className="stack-form" onSubmit={submit}>
        <label>{tr("New vault passphrase")}<input type="password" value={pass} onChange={(e) => setPass(e.target.value)} autoComplete="new-password" required /></label>
        <label>{tr("Type it again")}<input type="password" value={again} onChange={(e) => setAgain(e.target.value)} autoComplete="new-password" required /></label>
        <label>{tr("Your ZiraHive account password")}<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required /></label>
        {error && <p className="error" role="alert">{error}</p>}
        <div className="admin-row">
          <button className="primary" disabled={busy}>{tr("Save")}</button>
          {onCancel && <button type="button" onClick={onCancel}>{tr("Cancel")}</button>}
        </div>
      </form>
    </section>
  );
}

// ------------------------------------------------------------------ contents

interface Opened { item: VaultItem; fk: FileKey; meta: FileMeta }
interface Job { name: string; done: number; total: number; error?: string }

function kindOf(type: string) {
  return type.startsWith("image/") ? "image" : type.startsWith("video/") ? "video" : type.startsWith("audio/") ? "audio" : "file";
}

async function makeThumb(file: File): Promise<{ blob: Blob; width: number; height: number } | null> {
  try {
    let source: CanvasImageSource, w: number, h: number;
    if (file.type.startsWith("image/")) {
      const bmp = await createImageBitmap(file);
      source = bmp; w = bmp.width; h = bmp.height;
    } else if (file.type.startsWith("video/")) {
      const v = document.createElement("video");
      v.muted = true; v.preload = "metadata"; v.src = URL.createObjectURL(file);
      await new Promise((res, rej) => { v.onloadeddata = res; v.onerror = rej; setTimeout(rej, 8000); });
      v.currentTime = Math.min(1, (v.duration || 2) / 2);
      await new Promise((res) => { v.onseeked = res; setTimeout(res, 3000); });
      source = v; w = v.videoWidth; h = v.videoHeight;
      setTimeout(() => URL.revokeObjectURL(v.src), 1000);
    } else return null;
    const scale = Math.min(1, 480 / Math.max(w, h));
    const c = document.createElement("canvas");
    c.width = Math.max(1, Math.round(w * scale)); c.height = Math.max(1, Math.round(h * scale));
    c.getContext("2d")!.drawImage(source, 0, 0, c.width, c.height);
    const blob = await new Promise<Blob | null>((res) => c.toBlob(res, "image/webp", 0.8));
    return blob ? { blob, width: w, height: h } : null;
  } catch { return null; }  // e.g. HEIC, which browsers can't draw: shown with an icon instead
}

function Contents({ info, master, reload }: { info: VaultInfo; master: CryptoKey; reload: () => void }) {
  const [items, setItems] = useState<Opened[] | null>(null);
  const [thumbs, setThumbs] = useState<Record<string, string>>({});
  const made = useRef<string[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [viewing, setViewing] = useState<Opened | null>(null);
  const [changing, setChanging] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    const rows = await api.vaultItems();
    const opened: Opened[] = [];
    for (const item of rows) {
      try {
        const fk = await openFileKey(master, item.wrapped_key);
        opened.push({ item, fk, meta: await openMeta(fk, item.meta) });
      } catch { /* not ours to read: skip */ }
    }
    setItems(opened);
    // thumbnails, a few at a time
    const queue = opened.filter((o) => o.item.has_thumb);
    const worker = async () => {
      for (let o = queue.shift(); o; o = queue.shift()) {
        try {
          const res = await fetch(`/api/vault/items/${o.item.id}/thumb`, { credentials: "same-origin" });
          const plain = await open(o.fk.key, new Uint8Array(await res.arrayBuffer()));
          const url = URL.createObjectURL(new Blob([plain], { type: "image/webp" }));
          made.current.push(url);
          setThumbs((t) => ({ ...t, [o!.item.id]: url }));
        } catch { /* leave the icon */ }
      }
    };
    await Promise.all([worker(), worker(), worker(), worker()]);
  }, [master]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => () => { made.current.forEach(URL.revokeObjectURL); }, []);

  const uploadOne = async (file: File, index: number) => {
    const set = (c: Partial<Job>) => setJobs((js) => js.map((j, i) => (i === index ? { ...j, ...c } : j)));
    try {
      const { fk, wrapped } = await newFileKey(master);
      const thumb = await makeThumb(file);
      const meta: FileMeta = { name: file.name, type: file.type || "application/octet-stream", size: file.size, modified: file.lastModified,
        width: thumb?.width, height: thumb?.height };
      const size = encryptedSize(file.size);
      const item = await api.createVaultItem({ size, chunk_size: CHUNK, wrapped_key: wrapped, meta: await sealMeta(fk, meta) });
      const n = Math.max(1, Math.ceil(file.size / CHUNK));
      let offset = 0;
      for (let i = 0; i < n; i++) {
        const plain = new Uint8Array(await file.slice(i * CHUNK, (i + 1) * CHUNK).arrayBuffer());
        const cipher = await encryptChunk(fk, i, i === n - 1, plain);
        for (let attempt = 0; ; attempt++) {
          try { await api.vaultChunk(item.id, offset, cipher); break; }
          catch (e) { if (attempt >= 3) throw e; await new Promise((r) => setTimeout(r, 1000 * 2 ** attempt)); }
        }
        offset += cipher.length;
        set({ done: Math.min(file.size, (i + 1) * CHUNK) });
      }
      if (thumb) await api.vaultThumb(item.id, unb64(await seal(fk.key, new Uint8Array(await thumb.blob.arrayBuffer()))));
    } catch (e) { set({ error: e instanceof Error ? e.message : tr("Upload failed") }); }
  };

  const add = async (files: FileList | null) => {
    if (!files?.length) return;
    const list = Array.from(files);
    const start = jobs.length;
    setJobs((js) => [...js, ...list.map((f) => ({ name: f.name, done: 0, total: f.size }))]);
    for (let i = 0; i < list.length; i++) await uploadOne(list[i], start + i);
    await load();
    reload();
  };

  const remove = async (o: Opened) => {
    if (!confirm(tr("Delete \"{name}\" from the vault forever?", { name: o.meta.name }))) return;
    await api.deleteVaultItem(o.item.id);
    setViewing(null);
    await load();
    reload();
  };

  const rename = async (o: Opened) => {
    const name = prompt(tr("New name"), o.meta.name);
    if (!name?.trim() || name === o.meta.name) return;
    const meta = { ...o.meta, name: name.trim() };
    await api.renameVaultItem(o.item.id, await sealMeta(o.fk, meta));
    setViewing(viewing ? { ...o, meta } : null);
    await load();
  };

  if (changing) {
    return <ChangePassphrase raw={masterBytes()!} title={tr("Change vault passphrase")} onDone={() => { setChanging(false); reload(); }} onCancel={() => setChanging(false)} />;
  }

  const busy = jobs.some((j) => !j.error && j.done < j.total);
  return (
    <>
      <div className="vault-bar">
        <span className="muted">{tr("{n} files, {size}", { n: info.item_count, size: formatBytes(info.bytes) })} · {tr("Locks itself after 10 minutes without use")}</span>
        <input ref={input} type="file" multiple hidden onChange={(e) => { void add(e.target.files); e.target.value = ""; }} />
        <button className="primary" onClick={() => input.current?.click()}><Upload size={16} /> {tr("Add files")}</button>
        <button onClick={() => setChanging(true)}><KeyRound size={16} /> {tr("Change passphrase")}</button>
        <button onClick={lock}><Lock size={16} /> {tr("Lock")}</button>
      </div>
      {jobs.length > 0 && (
        <ul className="vault-jobs" aria-live="polite">
          {jobs.map((j, i) => (
            <li key={i}><span>{j.name}</span>
              {j.error ? <span className="error">{j.error}</span>
                : <progress max={j.total || 1} value={j.total ? j.done : 1} aria-label={tr("Encrypting and uploading {name}", { name: j.name })} />}
            </li>
          ))}
          {!busy && <li><button className="link-btn" onClick={() => setJobs([])}>{tr("Clear")}</button></li>}
        </ul>
      )}
      {items && items.length === 0 && (
        <div className="empty">
          <h2>{tr("Your vault is empty")}</h2>
          <p>{tr("Add private photos, ID scans, bank papers or anything else only you should see.")}</p>
        </div>
      )}
      <div className="vault-grid">
        {items?.map((o) => {
          const k = kindOf(o.meta.type);
          return (
            <button key={o.item.id} className="vault-tile" onClick={() => setViewing(o)} aria-label={tr("Open {name}", { name: o.meta.name })}>
              {thumbs[o.item.id] ? <img src={thumbs[o.item.id]} alt="" />
                : <span className="vault-icon">{k === "video" ? <Film size={30} /> : k === "audio" ? <Music size={30} /> : <FileText size={30} />}</span>}
              <span className="vault-name">{o.meta.name}</span>
            </button>
          );
        })}
      </div>
      {viewing && <Viewer o={viewing} onClose={() => setViewing(null)} onDelete={() => void remove(viewing)} onRename={() => void rename(viewing)} />}
    </>
  );
}

function Viewer({ o, onClose, onDelete, onRename }: { o: Opened; onClose: () => void; onDelete: () => void; onRename: () => void }) {
  const [url, setUrl] = useState<string | null>(null);
  const [done, setDone] = useState(0);
  const [error, setError] = useState("");
  useEffect(() => {
    let made: string | null = null, cancelled = false;
    (async () => {
      const res = await fetch(`/api/vault/items/${o.item.id}/data`, { credentials: "same-origin" });
      if (!res.ok || !res.body) throw new Error(String(res.status));
      const blob = await decryptStream(o.fk, res.body, o.item.size, o.item.chunk_size, setDone);
      if (cancelled) return;
      made = URL.createObjectURL(new Blob([blob], { type: o.meta.type }));
      setUrl(made);
    })().catch(() => setError(tr("This file couldn't be decrypted. It may be damaged.")));
    return () => { cancelled = true; if (made) URL.revokeObjectURL(made); };
  }, [o]);
  const k = kindOf(o.meta.type);
  return (
    <Dialog title={o.meta.name} onClose={onClose} wide>
      <div className="vault-view">
        {error ? <p className="error">{error}</p>
          : !url ? <progress max={o.item.size} value={done} aria-label={tr("Decrypting")} />
          : k === "image" ? <img src={url} alt={o.meta.name} />
          : k === "video" ? <video src={url} controls autoPlay playsInline />
          : k === "audio" ? <audio src={url} controls autoPlay />
          : <p className="muted">{tr("This file opens after you save it.")}</p>}
      </div>
      <p className="muted small">{formatBytes(o.meta.size)} · {tr("Added {date}", { date: dateFmt.format(new Date(o.item.created_at)) })}</p>
      <div className="admin-row">
        {url && <a className="button primary" href={url} download={o.meta.name}><Download size={16} /> {tr("Save")}</a>}
        <button onClick={onRename}><Pencil size={16} /> {tr("Rename")}</button>
        <button className="danger" onClick={onDelete}><Trash2 size={16} /> {tr("Delete forever")}</button>
      </div>
      <p className="muted small"><Link to="/files">{tr("Files outside the vault")}</Link></p>
    </Dialog>
  );
}
