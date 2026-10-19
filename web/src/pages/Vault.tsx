import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import ZoomImage from "../components/ZoomImage";
import { Link } from "react-router-dom";
import { Download, FileText, Folder, FolderInput, FolderPlus, KeyRound, Lock, Pencil, ShieldCheck, Trash2, Upload, Film, Music, Copy } from "lucide-react";
import { api, ApiError, formatBytes, type VaultInfo } from "../api";
import { t as tr, locale } from "../i18n";
import Dialog from "../components/Dialog";
import { createVault, rewrap, secureContextOk, sealMeta, unlockWithPassphrase, unlockWithRecovery } from "../vault/crypto";
import { decryptItem, encryptAndUpload, fillMissingThumbs, kindOf, loadThumbs, openAll, type Opened } from "../vault/files";
import { viewablePhoto } from "../heic";
import VaultCleanup from "../components/VaultCleanup";
import { allFolders, createFolder, deleteFolder, filesIn, filesWithin, folderOf, isFolder, join, moveTo, nameOf, parentOf, renameFolder, ROOT, subfolders } from "../vault/folders";
import { FolderNameDialog, MoveToFolderDialog } from "../components/VaultFolders";
import AutoLock from "../components/AutoLock";
import { lock, masterBytes, unlock, useVaultKey } from "../vault/session";

const MIN_PASSPHRASE = 10;
const dateFmt = new Intl.DateTimeFormat(locale(), { day: "numeric", month: "short", year: "numeric" });

export interface VaultCtx { info: VaultInfo; master: CryptoKey; reload: () => void }

/** Everything the vault needs before its contents can be shown: a secure page, a vault, and
 *  an unlocked key. Used by the Vault page and by Photos → Vault. */
export function VaultGate({ intro, children }: { intro?: ReactNode; children: (ctx: VaultCtx) => ReactNode }) {
  const key = useVaultKey();
  const [info, setInfo] = useState<VaultInfo | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => api.vault().then(setInfo).catch((e) => setError(e.message)), []);
  useEffect(() => { void load(); }, [load]);

  if (!secureContextOk()) {
    return (
      <div className="empty">
        <h2>{tr("The vault needs a secure connection")}</h2>
        <p>{tr("Open ZiraHive through https (for example your Tailscale address) or on this computer as localhost. Over plain http the browser doesn't allow encryption.")}</p>
      </div>
    );
  }
  if (error) return <p className="error">{error}</p>;
  if (!info) return <div aria-busy="true" />;
  if (!info.set_up) return <SetUp onDone={load} intro={intro} />;
  if (!key) return <Unlock info={info} onReset={load} />;
  return <>{children({ info, master: key, reload: load })}</>;
}

export default function VaultPage() {
  return (
    <div className="page vault-page">
      <header className="page-head"><h1><ShieldCheck size={26} aria-hidden /> {tr("Vault")}</h1></header>
      <VaultGate>{(ctx) => <Contents {...ctx} />}</VaultGate>
    </div>
  );
}

// ------------------------------------------------------------------ setting up

function SetUp({ onDone, intro }: { onDone: () => void; intro?: ReactNode }) {
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
      {intro ?? <h2>{tr("A locked space for private files")}</h2>}
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

export function Unlock({ info, onReset }: { info: VaultInfo; onReset: () => void }) {
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
      <p className="muted">{tr("{n} encrypted items, {size}", { n: info.item_count, size: formatBytes(info.bytes) })}</p>
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

export function ChangePassphrase({ raw, title, onDone, onCancel }: { raw: Uint8Array; title: string; onDone: () => void; onCancel?: () => void }) {
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

interface Job { name: string; done: number; total: number; error?: string }

function Contents({ master, reload }: VaultCtx) {
  const [items, setItems] = useState<Opened[] | null>(null);
  const [thumbs, setThumbs] = useState<Record<string, string>>({});
  const made = useRef<string[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [viewing, setViewing] = useState<Opened | null>(null);
  const [changing, setChanging] = useState(false);
  const [here, setHere] = useState(ROOT);
  const [naming, setNaming] = useState<"new" | "rename" | null>(null);
  const [moving, setMoving] = useState<Opened | null>(null);
  const [cleaning, setCleaning] = useState(false);
  const [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null);

  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);
  const load = useCallback(async () => {
    const opened = await openAll(master);
    setItems(opened);
    made.current.push(...await loadThumbs(opened, (id, u) => setThumbs((t) => ({ ...t, [id]: u })), () => !alive.current));
    made.current.push(...await fillMissingThumbs(opened, (id, u) => setThumbs((t) => ({ ...t, [id]: u })), () => !alive.current));
  }, [master]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => () => { made.current.forEach(URL.revokeObjectURL); }, []);
  // a folder that no longer exists (deleted, renamed elsewhere): go up until one does
  useEffect(() => {
    if (!items || here === ROOT) return;
    if (!allFolders(items).includes(here)) setHere(ROOT);
  }, [items, here]);

  const uploadOne = async (file: File, index: number, folder: string) => {
    const set = (c: Partial<Job>) => setJobs((js) => js.map((j, i) => (i === index ? { ...j, ...c } : j)));
    try { await encryptAndUpload(master, file, { folder }, (done) => set({ done })); }
    catch (e) { set({ error: e instanceof Error ? e.message : tr("Upload failed") }); }
  };

  const add = async (files: FileList | null) => {
    if (!files?.length) return;
    const list = Array.from(files);
    const start = jobs.length, folder = here;
    setJobs((js) => [...js, ...list.map((f) => ({ name: f.name, done: 0, total: f.size }))]);
    for (let i = 0; i < list.length; i++) await uploadOne(list[i], start + i, folder);
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

  const removeFolder = async () => {
    if (!items) return;
    const n = filesWithin(items, here).length;
    const ask = n === 0 ? tr("Delete the empty folder \"{name}\"?", { name: nameOf(here) })
      : n === 1 ? tr("Delete \"{name}\" and the 1 file in it forever?", { name: nameOf(here) })
      : tr("Delete \"{name}\" and the {n} files in it forever?", { name: nameOf(here), n });
    if (!confirm(ask)) return;
    setError("");
    try { await deleteFolder(items, here); setHere(parentOf(here)); }
    catch (e) { setError(e instanceof Error ? e.message : tr("Something went wrong")); }
    await load();
    reload();
  };

  if (changing) {
    return <ChangePassphrase raw={masterBytes()!} title={tr("Change vault passphrase")} onDone={() => { setChanging(false); reload(); }} onCancel={() => setChanging(false)} />;
  }

  const busy = jobs.some((j) => !j.error && j.done < j.total);
  const files = items ? items.filter((o) => !isFolder(o)) : [];
  const total = files.reduce((n, o) => n + o.meta.size, 0);
  const folders = items ? subfolders(items, here) : [];
  const shown = items ? filesIn(items, here) : [];
  const crumbs = here === ROOT ? [] : here.split("/").slice(1).map((_, i, parts) => "/" + parts.slice(0, i + 1).join("/"));
  return (
    <>
      <div className="vault-bar">
        <span className="muted">{tr("{n} files, {size}", { n: files.length, size: formatBytes(total) })}</span>
        <AutoLock />
        <input ref={input} type="file" multiple hidden onChange={(e) => { void add(e.target.files); e.target.value = ""; }} />
        <button className="primary" onClick={() => input.current?.click()}><Upload size={16} /> {tr("Add files")}</button>
        <button onClick={() => setNaming("new")}><FolderPlus size={16} /> {tr("New folder")}</button>
        <button onClick={() => setCleaning(true)} disabled={!files.length}><Copy size={16} /> {tr("Find duplicates")}</button>
        <button onClick={() => setChanging(true)}><KeyRound size={16} /> {tr("Change passphrase")}</button>
        <button onClick={lock}><Lock size={16} /> {tr("Lock")}</button>
      </div>
      <nav className="crumbs vault-crumbs" aria-label={tr("Folder")}>
        <button className={here === ROOT ? "here" : ""} onClick={() => setHere(ROOT)}><ShieldCheck size={16} aria-hidden /> {tr("Vault")}</button>
        {crumbs.map((p) => (
          <span key={p}><span className="sep" aria-hidden>›</span><button className={p === here ? "here" : ""} onClick={() => setHere(p)}>{nameOf(p)}</button></span>
        ))}
        {here !== ROOT && (
          <span className="vault-folder-actions">
            <button className="icon" onClick={() => setNaming("rename")} aria-label={tr("Rename folder")} title={tr("Rename folder")}><Pencil size={15} /></button>
            <button className="icon" onClick={() => void removeFolder()} aria-label={tr("Delete folder")} title={tr("Delete folder")}><Trash2 size={15} /></button>
          </span>
        )}
      </nav>
      {error && <p className="error" role="alert">{error}</p>}
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
      {items && items.length > 0 && here !== ROOT && folders.length === 0 && shown.length === 0 && (
        <p className="muted">{tr("This folder is empty. Add files, or move files here from another folder.")}</p>
      )}
      <div className="vault-grid">
        {folders.map((p) => {
          const n = filesWithin(items!, p).length;
          return (
            <button key={p} className="vault-tile vault-folder" onClick={() => setHere(p)} aria-label={tr("Open folder {name}", { name: nameOf(p) })}>
              <span className="vault-icon"><Folder size={34} /></span>
              <span className="vault-name">{nameOf(p)} <small className="muted">· {n}</small></span>
            </button>
          );
        })}
        {shown.map((o) => {
          const k = kindOf(o.meta.type, o.meta.name);
          return (
            <button key={o.item.id} className="vault-tile" onClick={() => setViewing(o)} aria-label={tr("Open {name}", { name: o.meta.name })}>
              {thumbs[o.item.id] ? <img src={thumbs[o.item.id]} alt="" />
                : <span className="vault-icon">{k === "video" ? <Film size={30} /> : k === "audio" ? <Music size={30} /> : <FileText size={30} />}</span>}
              <span className="vault-name">{o.meta.name}</span>
            </button>
          );
        })}
      </div>
      {cleaning && items && (
        <VaultCleanup what="documents" items={items} thumbs={thumbs} onChanged={() => { void load(); reload(); }} onClose={() => setCleaning(false)} />
      )}
      {viewing && <Viewer o={viewing} onClose={() => setViewing(null)} onDelete={() => void remove(viewing)} onRename={() => void rename(viewing)}
        onMove={() => setMoving(viewing)} />}
      {naming && items && (
        <FolderNameDialog items={items} parent={naming === "new" ? here : parentOf(here)} current={naming === "rename" ? here : undefined}
          onClose={() => setNaming(null)}
          onSave={async (name) => {
            if (naming === "new") { await createFolder(master, here, name); await load(); }
            else { await renameFolder(master, items, here, name); await load(); setHere(join(parentOf(here), name)); }
          }} />
      )}
      {moving && items && (
        <MoveToFolderDialog master={master} items={items} count={1} from={folderOf(moving)} onClose={() => setMoving(null)}
          onMove={async (folder) => { await moveTo(moving, folder); setViewing(null); await load(); }} />
      )}
    </>
  );
}

function Viewer({ o, onClose, onDelete, onRename, onMove }: { o: Opened; onClose: () => void; onDelete: () => void; onRename: () => void; onMove: () => void }) {
  const [url, setUrl] = useState<string | null>(null);      // the file itself, for Save
  const [shown, setShown] = useState<string | null>(null);  // what the page shows (HEIC as JPEG)
  const [done, setDone] = useState(0);
  const [error, setError] = useState("");
  const k = kindOf(o.meta.type, o.meta.name);
  useEffect(() => {
    const made: string[] = [];
    let cancelled = false;
    const link = (b: Blob) => { const u = URL.createObjectURL(b); made.push(u); return u; };
    decryptItem(o, setDone).then(async (blob) => {
      if (cancelled) return;
      setUrl(link(blob));
      const view = k === "image" ? await viewablePhoto(blob, o.meta.name).catch(() => blob) : blob;
      if (!cancelled) setShown(view === blob ? made[0] : link(view));
    }).catch(() => setError(tr("This file couldn't be decrypted. It may be damaged.")));
    return () => { cancelled = true; made.forEach((u) => URL.revokeObjectURL(u)); };
  }, [o, k]);
  return (
    <Dialog title={o.meta.name} onClose={onClose} wide>
      <div className="vault-view">
        {error ? <p className="error">{error}</p>
          : !url ? <progress max={o.item.size} value={done} aria-label={tr("Decrypting")} />
          : k === "image" ? (shown ? <ZoomImage src={shown} alt={o.meta.name} /> : <progress aria-label={tr("Getting the photo ready")} />)
          : k === "video" ? <video src={url} controls autoPlay playsInline />
          : k === "audio" ? <audio src={url} controls autoPlay />
          : <p className="muted">{tr("This file opens after you save it.")}</p>}
      </div>
      <p className="muted small">{formatBytes(o.meta.size)} · {tr("Added {date}", { date: dateFmt.format(new Date(o.item.created_at)) })}</p>
      <div className="admin-row">
        {url && <a className="button primary" href={url} download={o.meta.name}><Download size={16} /> {tr("Save")}</a>}
        <button onClick={onRename}><Pencil size={16} /> {tr("Rename")}</button>
        <button onClick={onMove}><FolderInput size={16} /> {tr("Move to folder")}</button>
        <button className="danger" onClick={onDelete}><Trash2 size={16} /> {tr("Delete forever")}</button>
      </div>
      <p className="muted small"><Link to="/files">{tr("Files outside the vault")}</Link></p>
    </Dialog>
  );
}
