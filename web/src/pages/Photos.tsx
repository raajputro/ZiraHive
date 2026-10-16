import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Upload, Play, ChevronLeft, ChevronRight, X, Download } from "lucide-react";
import { api, url, formatDuration, type Asset } from "../api";
import { useUploads } from "../uploads";
import { DropZone } from "./Files";

const monthFmt = new Intl.DateTimeFormat(undefined, { month: "long", year: "numeric" });
const dayFmt = new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", month: "short" });

export default function PhotosPage() {
  const [items, setItems] = useState<Asset[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<number | null>(null);
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
    } catch (e) { setError(e instanceof Error ? e.message : "Couldn't load photos"); }
    finally { setLoading(false); }
  }, [cursor, loading]);

  useEffect(() => { void load(true); /* eslint-disable-next-line */ }, []);
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

  const addFiles = (files: File[]) => enqueue(files.filter((f) => /^(image|video)\//.test(f.type) || /\.(heic|heif|dng)$/i.test(f.name)), "/Uploads");

  return (
    <DropZone onFiles={addFiles}>
      <div className="page">
        <header className="page-head">
          <h1>Photos</h1>
          <button className="primary" onClick={() => input.current?.click()}><Upload size={17} /> Upload photos</button>
          <input ref={input} type="file" multiple accept="image/*,video/*,.heic,.heif" hidden
            onChange={(e) => { addFiles(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
        </header>
        {error && <p className="error" role="alert">{error}</p>}
        {!loading && !error && items.length === 0 && (
          <div className="empty">
            <h2>No photos yet</h2>
            <p>Drop photos and videos here, or install the phone app to back up your camera roll automatically.</p>
          </div>
        )}
        {groups.map((m) => (
          <section key={m.month} className="month">
            <h2 className="month-title">{m.month}</h2>
            {m.days.map((g) => (
              <div key={g.day} className="day">
                <h3>{g.day}</h3>
                <div className="justified">
                  {g.items.map(({ a, i }) => {
                    const ratio = a.width && a.height ? a.width / a.height : 1;
                    return (
                      <button key={a.id} className="tile" style={{ flexGrow: ratio, aspectRatio: String(ratio), ["--r" as string]: ratio }}
                        onClick={() => setOpen(i)} aria-label={`Open ${a.filename}`}>
                        {a.thumb_ready ? <img src={url.thumb(a)} alt="" loading="lazy" /> : <span className="tile-wait" />}
                        {a.kind === "video" && <span className="tile-badge"><Play size={12} fill="currentColor" /> {formatDuration(a.duration)}</span>}
                      </button>
                    );
                  })}
                  <span className="justified-filler" />
                </div>
              </div>
            ))}
          </section>
        ))}
        <div ref={sentinel} className="sentinel">{loading && "Loading…"}</div>
      </div>
      {open !== null && items[open] && (
        <Lightbox items={items} index={open} onIndex={setOpen} onClose={() => setOpen(null)} />
      )}
    </DropZone>
  );
}

export function Lightbox({ items, index, onIndex, onClose }:
  { items: Asset[]; index: number; onIndex: (i: number) => void; onClose: () => void }) {
  const a = items[index];
  const [fallback, setFallback] = useState(false);
  useEffect(() => setFallback(false), [index]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight" && index < items.length - 1) onIndex(index + 1);
      if (e.key === "ArrowLeft" && index > 0) onIndex(index - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, items.length, onClose, onIndex]);

  return (
    <div className="lightbox" role="dialog" aria-modal="true" aria-label={a.filename}>
      <div className="lightbox-bar">
        <span>{a.filename}</span>
        <a className="icon" href={url.file(a, true)} aria-label="Download"><Download size={18} /></a>
        <button className="icon" onClick={onClose} aria-label="Close"><X size={20} /></button>
      </div>
      {index > 0 && <button className="lb-nav prev" onClick={() => onIndex(index - 1)} aria-label="Previous"><ChevronLeft size={30} /></button>}
      <div className="lightbox-stage">
        {a.kind === "video"
          ? <video key={a.id} src={url.file(a)} controls autoPlay />
          // Browsers other than Safari can't show HEIC; fall back to the WebP preview.
          : <img key={a.id} src={fallback ? url.thumb(a) : url.file(a)} alt={a.filename} onError={() => setFallback(true)} />}
      </div>
      {index < items.length - 1 && <button className="lb-nav next" onClick={() => onIndex(index + 1)} aria-label="Next"><ChevronRight size={30} /></button>}
    </div>
  );
}
