import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ZoomImage from "../components/ZoomImage";
import { NavLink } from "react-router-dom";
import { Upload, Play, ChevronLeft, ChevronRight, X, Download, Check, CheckSquare, FolderPlus, Maximize, Trash2, Lock, ShieldCheck } from "lucide-react";
import { api, url, formatDuration, type Asset, type Memory } from "../api";
import { useUploads } from "../uploads";
import { usePrefs } from "../prefs";
import { DropZone } from "./Files";
import { AddToAlbumDialog } from "./Albums";
import { PhotoSearchBox } from "./SmartPhotos";
import Dialog from "../components/Dialog";
import { VaultGate } from "./Vault";
import { masterKey } from "../vault/session";
import { moveToVault } from "../vault/photos";

import { locale, t as tr } from "../i18n";
const monthFmt = new Intl.DateTimeFormat(locale(), { month: "long", year: "numeric" });
const dayFmt = new Intl.DateTimeFormat(locale(), { weekday: "short", day: "numeric", month: "short" });

export function PhotoTabs() {
  return (
    <div className="watch-bar photo-bar">
      <nav className="lib-tabs photo-tabs" aria-label={tr("Photos")}>
        <NavLink to="/photos" end>{tr("Timeline")}</NavLink>
        <NavLink to="/photos/albums">{tr("Albums")}</NavLink>
        <NavLink to="/photos/people">{tr("People")}</NavLink>
        <NavLink to="/photos/cleanup">{tr("Clean up")}</NavLink>
        <NavLink to="/photos/vault"><Lock size={14} aria-hidden /> {tr("Vault")}</NavLink>
      </nav>
      <PhotoSearchBox />
    </div>
  );
}

/** A tile in a justified photo grid. In select mode a tap toggles the checkmark. */
export function Tile({ a, selected, selecting, onOpen, onToggle, thumbUrl }:
  { a: { id: string; width: number | null; height: number | null; kind: string; duration: number | null; thumb_ready: boolean; filename: string };
    selected?: boolean; selecting?: boolean; onOpen: () => void; onToggle?: () => void; thumbUrl: string }) {
  const ratio = a.width && a.height ? a.width / a.height : 1;
  return (
    <button className={`tile ${selected ? "selected" : ""}`} style={{ flexGrow: ratio, aspectRatio: String(ratio), ["--r" as string]: ratio }}
      onClick={selecting ? onToggle : onOpen} aria-pressed={selecting ? !!selected : undefined}
      aria-label={`${selecting ? tr("Select") : tr("Open")} ${a.filename}`}>
      {a.thumb_ready ? <img src={thumbUrl} alt="" loading="lazy" /> : <span className="tile-wait" />}
      {a.kind === "video" && <span className="tile-badge"><Play size={12} fill="currentColor" /> {formatDuration(a.duration)}</span>}
      {selecting && <span className="tile-check" aria-hidden>{selected && <Check size={14} />}</span>}
    </button>
  );
}

function OnThisDay({ memories, onOpen }: { memories: Memory[]; onOpen: (m: Memory, i: number) => void }) {
  if (!memories.length) return null;
  return (
    <section className="memories" aria-label={tr("On this day")}>
      <h2 className="shelf-title">{tr("On this day")}</h2>
      <div className="memory-row">
        {memories.map((m) => (
          <button key={m.year} className="memory" onClick={() => onOpen(m, 0)}>
            <img src={url.thumb(m.items[0])} alt="" />
            <span>{m.years_ago === 1 ? tr("1 year ago") : tr("{years_ago} years ago", { years_ago: m.years_ago })}</span>
            <small>{m.items.length} {m.items.length === 1 ? "photo" : "photos"}</small>
          </button>
        ))}
      </div>
    </section>
  );
}

export default function PhotosPage() {
  const [items, setItems] = useState<Asset[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [viewer, setViewer] = useState<{ items: Asset[]; index: number } | null>(null);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [albumPicker, setAlbumPicker] = useState(false);
  const sentinel = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const { enqueue, onComplete } = useUploads();

  const load = useCallback(async (reset = false) => {
    if (loading) return;
    setLoading(true);
    try {
      const page = await api.photos(reset ? null : cursor);
      setItems((prev) => (reset ? page.items : [...prev, ...page.items]));
      setCursor(page.next_cursor);
      setDone(!page.next_cursor);
      setError("");
    } catch (e) { setError(e instanceof Error ? e.message : tr("Couldn't load photos")); }
    finally { setLoading(false); }
  }, [cursor, loading]);

  useEffect(() => { void load(true); api.onThisDay().then(setMemories).catch(() => undefined); /* eslint-disable-next-line */ }, []);
  // thumbnails are made in the background; refresh shortly after uploads finish
  useEffect(() => onComplete(() => setTimeout(() => void load(true), 1500)), [onComplete, load]);

  useEffect(() => {
    const el = sentinel.current;
    if (!el || done) return;
    const io = new IntersectionObserver((e) => { if (e[0].isIntersecting) void load(); }, { rootMargin: "800px" });
    io.observe(el);
    return () => io.disconnect();
  }, [load, done]);

  const groups = useMemo(() => {
    const out: { month: string; days: { day: string; items: { a: Asset; i: number }[] }[] }[] = [];
    items.forEach((a, i) => {
      const d = new Date(a.taken_at ?? a.created_at);
      const month = monthFmt.format(d), day = dayFmt.format(d);
      let m = out[out.length - 1];
      if (!m || m.month !== month) { m = { month, days: [] }; out.push(m); }
      let g = m.days[m.days.length - 1];
      if (!g || g.day !== day) { g = { day, items: [] }; m.days.push(g); }
      g.items.push({ a, i });
    });
    return out;
  }, [items]);

  const toggle = (id: string) => setSelected((s) => {
    const n = new Set(s);
    if (n.has(id)) n.delete(id); else n.add(id);
    return n;
  });
  const stopSelecting = () => { setSelecting(false); setSelected(new Set()); };
  const [trashing, setTrashing] = useState(false);
  /** Drops photos that left the timeline (trash or vault) from everything on screen. */
  const dropFromView = (gone: Set<string>) => {
    if (!gone.size) return;
    setItems((prev) => prev.filter((a) => !gone.has(a.id)));
    setMemories((prev) => prev.map((m) => ({ ...m, items: m.items.filter((a) => !gone.has(a.id)) })).filter((m) => m.items.length));
    setSelected((s) => new Set([...s].filter((id) => !gone.has(id))));
    setViewer((v) => {
      if (!v) return v;
      const rest = v.items.filter((x) => !gone.has(x.id));
      return rest.length ? { items: rest, index: Math.min(v.index, rest.length - 1) } : null;
    });
  };
  const [vaultWaiting, setVaultWaiting] = useState<Asset[] | null>(null);  // waiting for the vault to be unlocked
  const [vaulting, setVaulting] = useState<number | null>(null);  // progress 0..1
  const runVault = async (master: CryptoKey, list: Asset[]) => {
    const gone = new Set<string>();
    setError("");
    try {
      for (let k = 0; k < list.length; k++) {
        setVaulting(k / list.length);
        await moveToVault(master, list[k], (f) => setVaulting((k + f) / list.length));
        gone.add(list[k].id);
      }
    } catch (e) {
      setError(tr("Couldn't move \"{filename}\" to the vault: {reason}", { filename: list[gone.size]?.filename ?? "", reason: e instanceof Error ? e.message : "" }));
    } finally {
      setVaulting(null);
      dropFromView(gone);
    }
    return gone;
  };
  const toVault = async (list: Asset[]) => {
    if (!list.length) return;
    const ask = list.length === 1
      ? tr("Move \"{filename}\" to your vault? It's encrypted on this device and removed from Photos, albums and search.", { filename: list[0].filename })
      : tr("Move {count} items to your vault? They're encrypted on this device and removed from Photos, albums and search.", { count: list.length });
    if (!confirm(ask)) return;
    const key = masterKey();
    if (!key) { setViewer(null); setVaultWaiting(list); return; }
    const gone = await runVault(key, list);
    if (selecting && gone.size === list.length) stopSelecting();
  };
  // Moves photos to the trash (restorable for 30 days) and drops them from what's on screen.
  const trash = async (ids: string[]) => {
    setTrashing(true);
    const gone = new Set<string>();
    try {
      for (const id of ids) { await api.trashAsset(id); gone.add(id); }
      setError("");
    } catch (e) { setError(e instanceof Error ? e.message : tr("Couldn't move to trash")); }
    finally {
      setTrashing(false);
      dropFromView(gone);
    }
    return gone;
  };
  const trashSelected = async () => {
    const ask = selected.size === 1
      ? tr("Move 1 item to the trash? You can restore it for 30 days.")
      : tr("Move {count} items to the trash? You can restore them for 30 days.", { count: selected.size });
    if (!confirm(ask)) return;
    const gone = await trash([...selected]);
    if (gone.size === selected.size) stopSelecting();
  };
  const trashFromViewer = async (a: Asset) => { await trash([a.id]); };
  const addFiles = (files: File[]) => enqueue(files.filter((f) => /^(image|video)\//.test(f.type) || /\.(heic|heif|dng)$/i.test(f.name)), "/Uploads");

  return (
    <DropZone onFiles={addFiles}>
      <div className="page">
        <header className="page-head">
          <h1>{tr("Photos")}</h1>
          {selecting ? (
            <>
              <span className="muted">{selected.size}{" "}{tr("selected")}</span>
              <button className="primary" disabled={!selected.size} onClick={() => setAlbumPicker(true)}><FolderPlus size={17} />{" "}{tr("Add to album")}</button>
              <button disabled={!selected.size || vaulting !== null} onClick={() => void toVault(items.filter((a) => selected.has(a.id)))}><Lock size={17} />{" "}{tr("Move to vault")}</button>
              <button className="danger" disabled={!selected.size || trashing} onClick={() => void trashSelected()}><Trash2 size={17} />{" "}{tr("Move to trash")}</button>
              <button onClick={stopSelecting}>{tr("Done")}</button>
            </>
          ) : (
            <>
              {items.length > 0 && <button onClick={() => setSelecting(true)}><CheckSquare size={17} />{" "}{tr("Select")}</button>}
              <button className="primary" onClick={() => input.current?.click()}><Upload size={17} />{" "}{tr("Upload photos")}</button>
            </>
          )}
          <input ref={input} type="file" multiple accept="image/*,video/*,.heic,.heif" hidden
            onChange={(e) => { addFiles(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
        </header>
        <PhotoTabs />
        {error && <p className="error" role="alert">{error}</p>}
        {vaulting !== null && (
          <div className="vault-busy" role="status"><span><Lock size={15} aria-hidden /> {tr("Encrypting and moving to your vault…")}</span><progress max={1} value={vaulting} /></div>
        )}
        {!selecting && <OnThisDay memories={memories} onOpen={(m, i) => setViewer({ items: m.items, index: i })} />}
        {!loading && !error && items.length === 0 && (
          <div className="empty">
            <h2>{tr("No photos yet")}</h2>
            <p>{tr("Drop photos and videos here, or open ZiraHive on your phone and press Upload photos to back up the camera roll.")}</p>
          </div>
        )}
        {groups.map((m) => (
          <section key={m.month} className="month">
            <h2 className="month-title">{m.month}</h2>
            {m.days.map((g) => (
              <div key={g.day} className="day">
                <h3>{g.day}</h3>
                <div className="justified">
                  {g.items.map(({ a, i }) => (
                    <Tile key={a.id} a={a} thumbUrl={url.thumb(a)} selecting={selecting} selected={selected.has(a.id)}
                      onToggle={() => toggle(a.id)} onOpen={() => setViewer({ items, index: i })} />
                  ))}
                  <span className="justified-filler" />
                </div>
              </div>
            ))}
          </section>
        ))}
        <div ref={sentinel} className="sentinel">{loading && tr("Loading…")}</div>
      </div>
      {viewer && viewer.items[viewer.index] && (
        <Lightbox items={viewer.items} index={viewer.index} onIndex={(i) => setViewer({ ...viewer, index: i })} onClose={() => setViewer(null)} onTrash={(a) => void trashFromViewer(a)}
          onVault={vaulting === null ? (a) => void toVault([a]) : undefined} />
      )}
      {vaultWaiting && (
        <Dialog title={tr("Unlock your vault")} onClose={() => setVaultWaiting(null)}>
          <VaultGate intro={<h2><ShieldCheck size={20} aria-hidden /> {tr("A locked place for private photos")}</h2>}>
            {(ctx) => <WhenReady run={() => {
              const list = vaultWaiting;
              setVaultWaiting(null);
              void runVault(ctx.master, list).then((gone) => { if (selecting && gone.size === list.length) stopSelecting(); });
            }} />}
          </VaultGate>
        </Dialog>
      )}
      {albumPicker && (
        <AddToAlbumDialog assetIds={[...selected]} onClose={() => setAlbumPicker(false)} onDone={() => { setAlbumPicker(false); stopSelecting(); }} />
      )}
    </DropZone>
  );
}

/** Calls `run` once, as soon as it is shown. */
function WhenReady({ run }: { run: () => void }) {
  const done = useRef(false);
  useEffect(() => { if (!done.current) { done.current = true; run(); } });
  return null;
}

export function Lightbox({ items, index, onIndex, onClose, onTrash, onVault }:
  { items: Asset[]; index: number; onIndex: (i: number) => void; onClose: () => void; onTrash?: (a: Asset) => void; onVault?: (a: Asset) => void }) {
  const a = items[index];
  const { lowData } = usePrefs();
  const [original, setOriginal] = useState(false);
  useEffect(() => setOriginal(false), [index]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight" && index < items.length - 1) onIndex(index + 1);
      if (e.key === "ArrowLeft" && index > 0) onIndex(index - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, items.length, onClose, onIndex]);

  // Screen-sized preview by default; low-data mode uses the small thumbnail; "Full size" loads
  // the original (HEIC photos as a full-size JPEG, so it works in every browser).
  const src = original ? url.view(a) : lowData ? url.thumb(a) : url.preview(a);
  return (
    <div className="lightbox" role="dialog" aria-modal="true" aria-label={a.filename}>
      <div className="lightbox-bar">
        <span>{a.filename}</span>
        {a.kind === "photo" && !original && (
          <button className="icon" onClick={() => setOriginal(true)} aria-label={tr("Show full size")} title={tr("Show full size")}><Maximize size={18} /></button>
        )}
        <a className="icon" href={url.file(a, true)} aria-label={tr("Download")}><Download size={18} /></a>
        {onVault && (
          <button className="icon" onClick={() => onVault(a)} aria-label={tr("Move to vault")} title={tr("Move to vault")}><Lock size={18} /></button>
        )}
        {onTrash && (
          <button className="icon" onClick={() => confirm(tr("Move \"{filename}\" to the trash?", { filename: a.filename })) && onTrash(a)}
            aria-label={tr("Move to trash")} title={tr("Move to trash")}><Trash2 size={18} /></button>
        )}
        <button className="icon" onClick={onClose} aria-label={tr("Close")}><X size={20} /></button>
      </div>
      {index > 0 && <button className="lb-nav prev" onClick={() => onIndex(index - 1)} aria-label={tr("Previous")}><ChevronLeft size={30} /></button>}
      <div className="lightbox-stage">
        {a.kind === "video"
          ? <video key={a.id} src={url.file(a)} controls autoPlay={!lowData} preload={lowData ? "none" : "metadata"}
              poster={a.thumb_ready ? url.thumb(a) : undefined} playsInline />
          : <ZoomImage key={a.id + src} src={src} alt={a.filename} onError={() => original && setOriginal(false)}
              onSwipe={(d) => { if (d === "next" && index < items.length - 1) onIndex(index + 1); if (d === "prev" && index > 0) onIndex(index - 1); }} />}
      </div>
      {index < items.length - 1 && <button className="lb-nav next" onClick={() => onIndex(index + 1)} aria-label={tr("Next")}><ChevronRight size={30} /></button>}
    </div>
  );
}
