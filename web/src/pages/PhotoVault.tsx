// Photos → Vault: private photos and videos, encrypted on this device. It is the same vault
// as the Vault page (one passphrase, one recovery key); this view shows its photos and videos.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, CheckSquare, Download, ImageUp, Lock, ShieldCheck, Trash2, Upload, X } from "lucide-react";
import { api, formatBytes } from "../api";
import { locale, t as tr } from "../i18n";
import { DropZone } from "./Files";
import { PhotoTabs, Tile } from "./Photos";
import { VaultGate, type VaultCtx } from "./Vault";
import { decryptItem, encryptAndUpload, isPhotoMeta, kindOf, loadThumbs, openAll, type Opened } from "../vault/files";
import { moveToPhotos } from "../vault/photos";
import { lock } from "../vault/session";

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

  const load = useCallback(async () => {
    const all = (await openAll(master)).filter((o) => isPhotoMeta(o.meta)).sort((x, y) => when(y) - when(x));
    if (!alive.current) return;
    setItems(all);
    made.current.push(...await loadThumbs(all, (id, u) => setThumbs((t) => ({ ...t, [id]: u })), () => !alive.current));
  }, [master]);
  useEffect(() => { alive.current = true; void load(); return () => { alive.current = false; }; }, [load]);
  useEffect(() => () => { made.current.forEach(URL.revokeObjectURL); }, []);

  const months = useMemo(() => {
    const out: { month: string; list: { o: Opened; i: number }[] }[] = [];
    (items ?? []).forEach((o, i) => {
      const month = monthFmt.format(new Date(when(o)));
      const last = out[out.length - 1];
      if (last?.month === month) last.list.push({ o, i }); else out.push({ month, list: [{ o, i }] });
    });
    return out;
  }, [items]);

  const add = async (files: File[]) => {
    const list = files.filter((f) => /^(image|video)\//.test(f.type) || /\.(heic|heif|dng)$/i.test(f.name));
    if (!list.length) return;
    const start = jobs.length;
    setJobs((js) => [...js, ...list.map((f) => ({ name: f.name, done: 0, total: f.size }))]);
    for (let i = 0; i < list.length; i++) {
      const set = (c: Partial<Job>) => setJobs((js) => js.map((j, k) => (k === start + i ? { ...j, ...c } : j)));
      try { await encryptAndUpload(master, list[i], { taken: list[i].lastModified }, (done) => set({ done })); }
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
  const stopSelecting = () => { setSelecting(false); setSelected(new Set()); };
  const toggle = (id: string) => setSelected((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });

  const jobsBusy = jobs.some((j) => !j.error && j.done < j.total);
  const viewingItems = items ?? [];
  return (
    <DropZone onFiles={(f) => void add(f)}>
      <div className="vault-bar">
        <span className="muted">
          <ShieldCheck size={15} aria-hidden /> {items ? (items.length === 1 ? tr("1 private item") : tr("{n} private items", { n: items.length })) : "…"}
          {" · "}{tr("Locks itself after 10 minutes without use")}
        </span>
        {selecting ? (
          <>
            <span className="muted">{selected.size}{" "}{tr("selected")}</span>
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
            <button onClick={lock}><Lock size={16} /> {tr("Lock")}</button>
          </>
        )}
      </div>
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
                a={{ id: o.item.id, width: o.meta.width ?? null, height: o.meta.height ?? null, kind: kindOf(o.meta.type) === "video" ? "video" : "photo",
                  duration: null, thumb_ready: !!thumbs[o.item.id], filename: o.meta.name }} />
            ))}
            <span className="justified-filler" />
          </div>
        </section>
      ))}
      {viewing !== null && viewingItems[viewing] && (
        <VaultLightbox items={viewingItems} index={viewing} thumbs={thumbs} onIndex={setViewing} onClose={() => setViewing(null)} busy={!!busy}
          onPutBack={(o) => void putBack([o]).then((g) => g.size && setViewing(null))}
          onDelete={(o) => void destroy([o]).then((g) => g.size && setViewing(null))} />
      )}
    </DropZone>
  );
}

function VaultLightbox({ items, index, thumbs, onIndex, onClose, onPutBack, onDelete, busy }: {
  items: Opened[]; index: number; thumbs: Record<string, string>; onIndex: (i: number) => void; onClose: () => void;
  onPutBack: (o: Opened) => void; onDelete: (o: Opened) => void; busy: boolean;
}) {
  const o = items[index];
  const [src, setSrc] = useState<string | null>(null);
  const [done, setDone] = useState(0);
  const [error, setError] = useState("");
  const [cantShow, setCantShow] = useState(false);
  useEffect(() => {
    let made: string | null = null, cancelled = false;
    setSrc(null); setDone(0); setError(""); setCantShow(false);
    decryptItem(o, setDone).then((blob) => {
      if (cancelled) return;
      made = URL.createObjectURL(blob);
      setSrc(made);
    }).catch(() => !cancelled && setError(tr("This file couldn't be decrypted. It may be damaged.")));
    return () => { cancelled = true; if (made) URL.revokeObjectURL(made); };
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

  const video = kindOf(o.meta.type) === "video";
  return (
    <div className="lightbox" role="dialog" aria-modal="true" aria-label={o.meta.name}>
      <div className="lightbox-bar">
        <span><Lock size={13} aria-hidden /> {o.meta.name} · {formatBytes(o.meta.size)}</span>
        {src && <a className="icon" href={src} download={o.meta.name} aria-label={tr("Save")} title={tr("Save")}><Download size={18} /></a>}
        <button className="icon" disabled={busy} onClick={() => onPutBack(o)} aria-label={tr("Move back to Photos")} title={tr("Move back to Photos")}><ImageUp size={18} /></button>
        <button className="icon" disabled={busy} onClick={() => onDelete(o)} aria-label={tr("Delete forever")} title={tr("Delete forever")}><Trash2 size={18} /></button>
        <button className="icon" onClick={onClose} aria-label={tr("Close")}><X size={20} /></button>
      </div>
      {index > 0 && <button className="lb-nav prev" onClick={() => onIndex(index - 1)} aria-label={tr("Previous")}><ChevronLeft size={30} /></button>}
      <div className="lightbox-stage">
        {error ? <p className="error">{error}</p>
          : !src ? <progress className="vault-decrypt" max={o.item.size} value={done} aria-label={tr("Decrypting")} />
          : video ? <video key={o.item.id} src={src} controls autoPlay playsInline />
          : cantShow ? (
            <div className="vault-noshow">
              {thumbs[o.item.id] && <img src={thumbs[o.item.id]} alt={o.meta.name} />}
              <p className="muted">{tr("This browser can't show this photo at full size. Save it to see the original.")}</p>
            </div>
          ) : <img key={o.item.id} src={src} alt={o.meta.name} onError={() => setCantShow(true)} />}
      </div>
      {index < items.length - 1 && <button className="lb-nav next" onClick={() => onIndex(index + 1)} aria-label={tr("Next")}><ChevronRight size={30} /></button>}
    </div>
  );
}
