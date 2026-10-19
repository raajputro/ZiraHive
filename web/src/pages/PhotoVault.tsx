// Photos → Vault: private photos and videos, encrypted on this device. It is the same vault
// as the Vault page (one passphrase, one recovery key); this view shows its photos and videos.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, CheckSquare, Download, Folder, FolderInput, FolderPlus, ImageUp, Lock, Pencil, ShieldCheck, Sparkles, Trash2, Upload, X } from "lucide-react";
import { api, formatBytes } from "../api";
import { locale, t as tr } from "../i18n";
import { DropZone } from "./Files";
import { PhotoTabs, Tile } from "./Photos";
import { VaultGate, type VaultCtx } from "./Vault";
import { decryptItem, encryptAndUpload, isPhotoMeta, fillMissingThumbs, kindOf, loadThumbs, openAll, type Opened } from "../vault/files";
import { moveToPhotos } from "../vault/photos";
import { viewablePhoto } from "../heic";
import VaultCleanup from "../components/VaultCleanup";
import AutoLock from "../components/AutoLock";
import { lock } from "../vault/session";
import { allFolders, createFolder, deleteFolder, filesWithin, folderOf, join, moveTo, nameOf, parentOf, renameFolder, ROOT } from "../vault/folders";
import { FolderNameDialog, MoveToFolderDialog } from "../components/VaultFolders";

const monthFmt = new Intl.DateTimeFormat(locale(), { month: "long", year: "numeric" });
const when = (o: Opened) => o.meta.taken ?? o.meta.modified ?? new Date(o.item.created_at).getTime();

export default function PhotoVaultPage() {
  return (
    <div className="page">
      <header className="page-head"><h1>{tr("Photos")}</h1></header>
      <PhotoTabs />
      <VaultGate intro={<h2><ShieldCheck size={20} aria-hidden /> {tr("A locked place for private photos")}</h2>}>
        {(ctx) => <Contents {...ctx} />}
      </VaultGate>
    </div>
  );
}

interface Job { name: string; done: number; total: number; error?: string }

function Contents({ master, reload }: VaultCtx) {
  const [items, setItems] = useState<Opened[] | null>(null);
  const [thumbs, setThumbs] = useState<Record<string, string>>({});
  const made = useRef<string[]>([]);
  const alive = useRef(true);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [viewing, setViewing] = useState<number | null>(null);
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<{ label: string; fraction: number } | null>(null);
  const [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const [everything, setEverything] = useState<Opened[]>([]);  // folders and non-photo files too
  const [folder, setFolder] = useState<string | null>(null);  // null = all photos
  const [naming, setNaming] = useState<"new" | "rename" | null>(null);
  const [moving, setMoving] = useState<Opened[] | null>(null);
  const [cleaning, setCleaning] = useState(false);

  const load = useCallback(async () => {
    const opened = await openAll(master);
    const all = opened.filter((o) => isPhotoMeta(o.meta)).sort((x, y) => when(y) - when(x));
    if (!alive.current) return;
    setEverything(opened);
    setItems(all);
    made.current.push(...await loadThumbs(all, (id, u) => setThumbs((t) => ({ ...t, [id]: u })), () => !alive.current));
    made.current.push(...await fillMissingThumbs(all, (id, u) => setThumbs((t) => ({ ...t, [id]: u })), () => !alive.current));
  }, [master]);
  const folders = useMemo(() => allFolders(everything), [everything]);
  useEffect(() => { if (folder && folder !== ROOT && everything.length && !folders.includes(folder)) setFolder(null); }, [folders, folder, everything.length]);
  const shownItems = useMemo(() => (items ?? []).filter((o) => folder === null || folderOf(o) === folder), [items, folder]);
  useEffect(() => { alive.current = true; void load(); return () => { alive.current = false; }; }, [load]);
  useEffect(() => () => { made.current.forEach(URL.revokeObjectURL); }, []);

  const months = useMemo(() => {
    const out: { month: string; list: { o: Opened; i: number }[] }[] = [];
    shownItems.forEach((o, i) => {
      const month = monthFmt.format(new Date(when(o)));
      const last = out[out.length - 1];
      if (last?.month === month) last.list.push({ o, i }); else out.push({ month, list: [{ o, i }] });
    });
    return out;
  }, [shownItems]);

  const add = async (files: File[]) => {
    const list = files.filter((f) => /^(image|video)\//.test(f.type) || /\.(heic|heif|dng)$/i.test(f.name));
    if (!list.length) return;
    const start = jobs.length;
    setJobs((js) => [...js, ...list.map((f) => ({ name: f.name, done: 0, total: f.size }))]);
    for (let i = 0; i < list.length; i++) {
      const set = (c: Partial<Job>) => setJobs((js) => js.map((j, k) => (k === start + i ? { ...j, ...c } : j)));
      try { await encryptAndUpload(master, list[i], { taken: list[i].lastModified, folder: folder ?? ROOT }, (done) => set({ done })); }
      catch (e) { set({ error: e instanceof Error ? e.message : tr("Upload failed") }); }
    }
    await load();
    reload();
  };

  /** Runs `fn` on each item in turn with one progress bar; stops at the first failure. */
  const each = async (list: Opened[], label: string, fn: (o: Opened, p: (f: number) => void) => Promise<void>) => {
    const gone = new Set<string>();
    setError("");
    try {
      for (let k = 0; k < list.length; k++) {
        setBusy({ label, fraction: k / list.length });
        await fn(list[k], (f) => setBusy({ label, fraction: (k + f) / list.length }));
        gone.add(list[k].item.id);
      }
    } catch (e) { setError(e instanceof Error ? e.message : tr("Something went wrong")); }
    finally {
      setBusy(null);
      if (gone.size) {
        setItems((prev) => prev?.filter((o) => !gone.has(o.item.id)) ?? null);
        setSelected((s) => new Set([...s].filter((id) => !gone.has(id))));
        reload();
      }
    }
    return gone;
  };
  const putBack = (list: Opened[]) => each(list, tr("Moving back to Photos…"), (o, p) => moveToPhotos(o, p));
  const destroy = async (list: Opened[]) => {
    const ask = list.length === 1
      ? tr("Delete \"{name}\" from the vault forever?", { name: list[0].meta.name })
      : tr("Delete {count} items from the vault forever?", { count: list.length });
    if (!confirm(ask)) return new Set<string>();
    return each(list, tr("Deleting…"), async (o) => { await api.deleteVaultItem(o.item.id); });
  };
  const chosen = () => (items ?? []).filter((o) => selected.has(o.item.id));
  const removeFolder = async () => {
    if (!folder || folder === ROOT) return;
    const n = filesWithin(everything, folder).length;
    const ask = n === 0 ? tr("Delete the empty folder \"{name}\"?", { name: nameOf(folder) })
      : n === 1 ? tr("Delete \"{name}\" and the 1 file in it forever?", { name: nameOf(folder) })
      : tr("Delete \"{name}\" and the {n} files in it forever?", { name: nameOf(folder), n });
    if (!confirm(ask)) return;
    setError("");
    try { await deleteFolder(everything, folder); setFolder(null); }
    catch (e) { setError(e instanceof Error ? e.message : tr("Something went wrong")); }
    await load();
    reload();
  };
  const stopSelecting = () => { setSelecting(false); setSelected(new Set()); };
  const toggle = (id: string) => setSelected((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });

  const jobsBusy = jobs.some((j) => !j.error && j.done < j.total);
  const viewingItems = shownItems;
  const countIn = (p: string) => (items ?? []).filter((o) => folderOf(o) === p).length;
  return (
    <DropZone onFiles={(f) => void add(f)}>
      <div className="vault-bar">
        <span className="muted">
          <ShieldCheck size={15} aria-hidden /> {items ? (items.length === 1 ? tr("1 private item") : tr("{n} private items", { n: items.length })) : "…"}
        </span>
        <AutoLock />
        {selecting ? (
          <>
            <span className="muted">{selected.size}{" "}{tr("selected")}</span>
            <button disabled={!selected.size || !!busy} onClick={() => setMoving(chosen())}><FolderInput size={16} /> {tr("Move to folder")}</button>
            <button disabled={!selected.size || !!busy} onClick={() => void putBack(chosen()).then((g) => g.size && stopSelecting())}>
              <ImageUp size={16} /> {tr("Move back to Photos")}</button>
            <button className="danger" disabled={!selected.size || !!busy} onClick={() => void destroy(chosen()).then((g) => g.size && stopSelecting())}>
              <Trash2 size={16} /> {tr("Delete forever")}</button>
            <button onClick={stopSelecting}>{tr("Done")}</button>
          </>
        ) : (
          <>
            {!!items?.length && <button onClick={() => setSelecting(true)}><CheckSquare size={16} /> {tr("Select")}</button>}
            <input ref={input} type="file" multiple accept="image/*,video/*,.heic,.heif" hidden
              onChange={(e) => { void add(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
            <button className="primary" onClick={() => input.current?.click()}><Upload size={16} /> {tr("Add photos")}</button>
            <button onClick={() => setNaming("new")}><FolderPlus size={16} /> {tr("New folder")}</button>
            <button onClick={() => setCleaning(true)} disabled={!items?.length}><Sparkles size={16} /> {tr("Clean up")}</button>
            <button onClick={lock}><Lock size={16} /> {tr("Lock")}</button>
          </>
        )}
      </div>
      {items !== null && (folders.length > 0 || folder !== null) && (
        <div className="vault-chips" role="tablist" aria-label={tr("Folders")}>
          <button role="tab" aria-selected={folder === null} className={folder === null ? "on" : ""} onClick={() => setFolder(null)}>
            {tr("All")} <small>{items.length}</small></button>
          <button role="tab" aria-selected={folder === ROOT} className={folder === ROOT ? "on" : ""} onClick={() => setFolder(ROOT)}>
            <ShieldCheck size={14} aria-hidden /> {tr("Not in a folder")} <small>{countIn(ROOT)}</small></button>
          {folders.map((p) => (
            <button key={p} role="tab" aria-selected={folder === p} className={folder === p ? "on" : ""} onClick={() => setFolder(p)} title={p.slice(1)}>
              <Folder size={14} aria-hidden /> {p.split("/").length > 2 ? p.slice(1).split("/").join(" › ") : nameOf(p)} <small>{countIn(p)}</small></button>
          ))}
          {folder && folder !== ROOT && (
            <span className="vault-folder-actions">
              <button className="icon" onClick={() => setNaming("rename")} aria-label={tr("Rename folder")} title={tr("Rename folder")}><Pencil size={15} /></button>
              <button className="icon" onClick={() => void removeFolder()} aria-label={tr("Delete folder")} title={tr("Delete folder")}><Trash2 size={15} /></button>
            </span>
          )}
        </div>
      )}
      {busy && (
        <div className="vault-busy" role="status"><span>{busy.label}</span><progress max={1} value={busy.fraction} /></div>
      )}
      {error && <p className="error" role="alert">{error}</p>}
      {jobs.length > 0 && (
        <ul className="vault-jobs" aria-live="polite">
          {jobs.map((j, i) => (
            <li key={i}><span>{j.name}</span>
              {j.error ? <span className="error">{j.error}</span>
                : <progress max={j.total || 1} value={j.total ? j.done : 1} aria-label={tr("Encrypting and uploading {name}", { name: j.name })} />}
            </li>
          ))}
          {!jobsBusy && <li><button className="link-btn" onClick={() => setJobs([])}>{tr("Clear")}</button></li>}
        </ul>
      )}
      {items === null && <p className="muted">{tr("Unlocking…")}</p>}
      {items !== null && items.length > 0 && shownItems.length === 0 && (
        <p className="muted">{tr("No photos in this folder yet. Add photos here, or select photos and use Move to folder.")}</p>
      )}
      {items?.length === 0 && (
        <div className="empty">
          <h2>{tr("No private photos yet")}</h2>
          <p>{tr("In Photos, open a photo or use Select, then press Move to vault. Or add photos from this device here. They're encrypted before they leave it.")}</p>
        </div>
      )}
      {months.map((m) => (
        <section key={m.month} className="month">
          <h2 className="month-title">{m.month}</h2>
          <div className="justified">
            {m.list.map(({ o, i }) => (
              <Tile key={o.item.id} thumbUrl={thumbs[o.item.id] ?? ""} selecting={selecting} selected={selected.has(o.item.id)}
                onToggle={() => toggle(o.item.id)} onOpen={() => setViewing(i)}
                a={{ id: o.item.id, width: o.meta.width ?? null, height: o.meta.height ?? null, kind: kindOf(o.meta.type, o.meta.name) === "video" ? "video" : "photo",
                  duration: null, thumb_ready: !!thumbs[o.item.id], filename: o.meta.name }} />
            ))}
            <span className="justified-filler" />
          </div>
        </section>
      ))}
      {viewing !== null && viewingItems[viewing] && (
        <VaultLightbox items={viewingItems} index={viewing} thumbs={thumbs} onIndex={setViewing} onClose={() => setViewing(null)} busy={!!busy}
          onPutBack={(o) => void putBack([o]).then((g) => g.size && setViewing(null))}
          onDelete={(o) => void destroy([o]).then((g) => g.size && setViewing(null))}
          onMove={(o) => setMoving([o])} />
      )}
      {naming && (
        <FolderNameDialog items={everything} parent={naming === "new" ? (folder && folder !== ROOT ? folder : ROOT) : parentOf(folder!)}
          current={naming === "rename" ? folder! : undefined} onClose={() => setNaming(null)}
          onSave={async (name) => {
            if (naming === "new") { const parent = folder && folder !== ROOT ? folder : ROOT; await createFolder(master, parent, name); await load(); setFolder(join(parent, name)); }
            else { await renameFolder(master, everything, folder!, name); await load(); setFolder(join(parentOf(folder!), name)); }
          }} />
      )}
      {moving && (
        <MoveToFolderDialog master={master} items={everything} count={moving.length}
          from={new Set(moving.map(folderOf)).size === 1 ? folderOf(moving[0]) : undefined} onClose={() => setMoving(null)}
          onMove={async (to) => {
            for (const o of moving) await moveTo(o, to);
            setViewing(null); stopSelecting(); await load();
          }} />
      )}
      {cleaning && items && (
        <VaultCleanup what="photos" items={items} thumbs={thumbs} onChanged={() => void load()} onClose={() => setCleaning(false)} />
      )}
    </DropZone>
  );
}

function VaultLightbox({ items, index, thumbs, onIndex, onClose, onPutBack, onDelete, onMove, busy }: {
  items: Opened[]; index: number; thumbs: Record<string, string>; onIndex: (i: number) => void; onClose: () => void;
  onPutBack: (o: Opened) => void; onDelete: (o: Opened) => void; onMove: (o: Opened) => void; busy: boolean;
}) {
  const o = items[index];
  const [src, setSrc] = useState<string | null>(null);      // the file itself, for Save
  const [shown, setShown] = useState<string | null>(null);  // what the page shows (HEIC as JPEG)
  const [done, setDone] = useState(0);
  const [error, setError] = useState("");
  const [cantShow, setCantShow] = useState(false);
  useEffect(() => {
    const made: string[] = [];
    let cancelled = false;
    const link = (b: Blob) => { const u = URL.createObjectURL(b); made.push(u); return u; };
    setSrc(null); setShown(null); setDone(0); setError(""); setCantShow(false);
    decryptItem(o, setDone).then(async (blob) => {
      if (cancelled) return;
      const original = link(blob);
      setSrc(original);
      if (kindOf(o.meta.type, o.meta.name) === "video") { setShown(original); return; }
      const view = await viewablePhoto(blob, o.meta.name).catch(() => null);
      if (cancelled) return;
      if (view === null) setCantShow(true);
      else setShown(view === blob ? original : link(view));
    }).catch(() => !cancelled && setError(tr("This file couldn't be decrypted. It may be damaged.")));
    return () => { cancelled = true; made.forEach((u) => URL.revokeObjectURL(u)); };
  }, [o]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight" && index < items.length - 1) onIndex(index + 1);
      if (e.key === "ArrowLeft" && index > 0) onIndex(index - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, items.length, onClose, onIndex]);

  const video = kindOf(o.meta.type, o.meta.name) === "video";
  return (
    <div className="lightbox" role="dialog" aria-modal="true" aria-label={o.meta.name}>
      <div className="lightbox-bar">
        <span><Lock size={13} aria-hidden /> {o.meta.name} · {formatBytes(o.meta.size)}</span>
        {src && <a className="icon" href={src} download={o.meta.name} aria-label={tr("Save")} title={tr("Save")}><Download size={18} /></a>}
        <button className="icon" disabled={busy} onClick={() => onMove(o)} aria-label={tr("Move to folder")} title={tr("Move to folder")}><FolderInput size={18} /></button>
        <button className="icon" disabled={busy} onClick={() => onPutBack(o)} aria-label={tr("Move back to Photos")} title={tr("Move back to Photos")}><ImageUp size={18} /></button>
        <button className="icon" disabled={busy} onClick={() => onDelete(o)} aria-label={tr("Delete forever")} title={tr("Delete forever")}><Trash2 size={18} /></button>
        <button className="icon" onClick={onClose} aria-label={tr("Close")}><X size={20} /></button>
      </div>
      {index > 0 && <button className="lb-nav prev" onClick={() => onIndex(index - 1)} aria-label={tr("Previous")}><ChevronLeft size={30} /></button>}
      <div className="lightbox-stage">
        {error ? <p className="error">{error}</p>
          : !src ? <progress className="vault-decrypt" max={o.item.size} value={done} aria-label={tr("Decrypting")} />
          : video ? <video key={o.item.id} src={src} controls autoPlay playsInline />
          : !shown && !cantShow ? <progress className="vault-decrypt" aria-label={tr("Getting the photo ready")} />
          : cantShow ? (
            <div className="vault-noshow">
              {thumbs[o.item.id] && <img src={thumbs[o.item.id]} alt={o.meta.name} />}
              <p className="muted">{tr("This browser can't show this photo at full size. Save it to see the original.")}</p>
            </div>
          ) : <img key={o.item.id} src={shown!} alt={o.meta.name} onError={() => setCantShow(true)} />}
      </div>
      {index < items.length - 1 && <button className="lb-nav next" onClick={() => onIndex(index + 1)} aria-label={tr("Next")}><ChevronRight size={30} /></button>}
    </div>
  );
}
