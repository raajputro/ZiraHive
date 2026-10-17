import { useEffect, useRef, useState, type PointerEvent as RPointerEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, Camera, ChevronLeft, ChevronRight, ImagePlus, Maximize, Pencil, RotateCw, ScanLine, Trash2, Wand2 } from "lucide-react";
import { api, ApiError } from "../api";
import { digits, t as tr } from "../i18n";
import { applyFilter, detectCorners, fullFrame, loadPicture, rotate, straighten, toJpeg, type Filter, type Pt } from "../scanner/image";

interface Page { key: number; source: HTMLCanvasElement; corners: Pt[]; turns: number; filter: Filter; result: HTMLCanvasElement; thumb: string }

let nextKey = 1;

function render(p: Omit<Page, "result" | "thumb">): Page {
  const result = applyFilter(rotate(straighten(p.source, p.corners), p.turns), p.filter);
  const t = document.createElement("canvas");
  const k = 220 / Math.max(result.width, result.height);
  t.width = Math.round(result.width * k); t.height = Math.round(result.height * k);
  t.getContext("2d")!.drawImage(result, 0, 0, t.width, t.height);
  return { ...p, result, thumb: t.toDataURL("image/jpeg", 0.7) };
}

function defaultTitle() {
  const d = new Date();
  return digits(`${tr("Scan")} ${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}.${String(d.getMinutes()).padStart(2, "0")}`);
}

export default function ScanPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [pages, setPages] = useState<Page[]>([]);
  const [editing, setEditing] = useState<number | null>(null);
  const [title, setTitle] = useState(defaultTitle);
  const [folder, setFolder] = useState(params.get("folder") || "/Scans");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const camera = useRef<HTMLInputElement>(null);
  const pick = useRef<HTMLInputElement>(null);

  const add = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(tr("Finding the page…"));
    try {
      const added: Page[] = [];
      for (const f of Array.from(files)) {
        const source = await loadPicture(f);
        added.push(render({ key: nextKey++, source, corners: detectCorners(source), turns: 0, filter: "enhance" }));
      }
      setPages((ps) => [...ps, ...added]);
      if (added.length === 1) setEditing(added[0].key);
    } catch { setError(tr("That picture couldn't be opened.")); }
    finally { setBusy(""); }
  };

  const update = (key: number, change: Partial<Page>) =>
    setPages((ps) => ps.map((p) => (p.key === key ? render({ ...p, ...change }) : p)));
  const move = (i: number, d: number) => setPages((ps) => { const n = [...ps]; [n[i], n[i + d]] = [n[i + d], n[i]]; return n; });

  const save = async () => {
    setError("");
    setBusy(tr("Uploading pages…"));
    let id: string | null = null;
    try {
      id = (await api.startScan()).id;
      for (let i = 0; i < pages.length; i++) {
        setBusy(tr("Uploading page {n} of {total}…", { n: i + 1, total: pages.length }));
        await api.scanPage(id, i + 1, await toJpeg(pages[i].result));
      }
      setBusy(tr("Reading the text and making the PDF…"));
      const asset = await api.finishScan(id, title.trim() || defaultTitle(), folder);
      navigate(`/files${asset.folder === "/" ? "" : asset.folder.split("/").map(encodeURIComponent).join("/")}`,
        { state: { saved: asset.filename } });
    } catch (e) {
      if (id) void api.cancelScan(id).catch(() => undefined);
      setError(e instanceof ApiError ? e.message : tr("Couldn't save the scan"));
    } finally { setBusy(""); }
  };

  const current = pages.find((p) => p.key === editing);
  return (
    <div className="page scan-page">
      <Link to="/files" className="back"><ArrowLeft size={18} /> {tr("Files")}</Link>
      <header className="page-head"><h1><ScanLine size={24} aria-hidden /> {tr("Scan documents")}</h1></header>
      <input ref={camera} type="file" accept="image/*" capture="environment" hidden onChange={(e) => { void add(e.target.files); e.target.value = ""; }} />
      <input ref={pick} type="file" accept="image/*" multiple hidden onChange={(e) => { void add(e.target.files); e.target.value = ""; }} />

      {current ? (
        <Editor page={current} onChange={(c) => update(current.key, c)} onDone={() => setEditing(null)} />
      ) : (
        <>
          <div className="admin-row">
            <button className="primary" onClick={() => camera.current?.click()}><Camera size={17} /> {tr("Take a photo")}</button>
            <button onClick={() => pick.current?.click()}><ImagePlus size={17} /> {tr("Choose pictures")}</button>
          </div>
          {pages.length === 0 && !busy && (
            <div className="empty">
              <h2>{tr("Turn paper into a PDF you can search")}</h2>
              <p>{tr("Put the page on a dark table, take a photo from above, and ZiraHive straightens and cleans it. Add as many pages as you like. The words are read in Bangla and English, so you can find the document later by searching for anything written on it.")}</p>
            </div>
          )}
          {pages.length > 0 && (
            <ol className="scan-pages" aria-label={tr("Pages")}>
              {pages.map((p, i) => (
                <li key={p.key}>
                  <img src={p.thumb} alt={tr("Page {n}", { n: i + 1 })} />
                  <span className="scan-n">{digits(String(i + 1))}</span>
                  <div className="scan-tools">
                    <button className="icon" disabled={i === 0} onClick={() => move(i, -1)} aria-label={tr("Move page {n} earlier", { n: i + 1 })}><ChevronLeft size={16} /></button>
                    <button className="icon" onClick={() => setEditing(p.key)} aria-label={tr("Adjust page {n}", { n: i + 1 })}><Pencil size={16} /></button>
                    <button className="icon" onClick={() => setPages((ps) => ps.filter((x) => x.key !== p.key))} aria-label={tr("Remove page {n}", { n: i + 1 })}><Trash2 size={16} /></button>
                    <button className="icon" disabled={i === pages.length - 1} onClick={() => move(i, 1)} aria-label={tr("Move page {n} later", { n: i + 1 })}><ChevronRight size={16} /></button>
                  </div>
                </li>
              ))}
            </ol>
          )}
          {pages.length > 0 && (
            <form className="stack-form scan-save" onSubmit={(e) => { e.preventDefault(); void save(); }}>
              <label>{tr("Name")}<input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={180} required /></label>
              <label>{tr("Save in folder")}<input value={folder} onChange={(e) => setFolder(e.target.value)} required /></label>
              <button className="primary" disabled={!!busy}>{tr("Save as PDF ({n} pages)", { n: pages.length })}</button>
            </form>
          )}
        </>
      )}
      {busy && <p role="status" className="muted">{busy}</p>}
      {error && <p className="error" role="alert">{error}</p>}
    </div>
  );
}

const FILTERS: [Filter, string][] = [["enhance", "Enhanced"], ["color", "Colour"], ["gray", "Grey"], ["bw", "Black and white"]];

function Editor({ page, onChange, onDone }: { page: Page; onChange: (c: Partial<Page>) => void; onDone: () => void }) {
  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [corners, setCorners] = useState(page.corners);
  const [drag, setDrag] = useState<number | null>(null);
  const [scale, setScale] = useState(1);
  const [preview, setPreview] = useState(false);

  useEffect(() => {
    const c = canvas.current!, src = preview ? page.result : page.source;
    const fit = Math.min(1, (box.current?.clientWidth ?? 600) / src.width, (window.innerHeight * 0.62) / src.height);
    c.width = Math.round(src.width * fit); c.height = Math.round(src.height * fit);
    c.getContext("2d")!.drawImage(src, 0, 0, c.width, c.height);
    setScale(fit);
  }, [page, preview]);

  const at = (e: RPointerEvent) => {
    const r = canvas.current!.getBoundingClientRect();
    return { x: Math.max(0, Math.min(page.source.width, (e.clientX - r.left) / scale)), y: Math.max(0, Math.min(page.source.height, (e.clientY - r.top) / scale)) };
  };
  const commit = (c: Pt[]) => { setCorners(c); onChange({ corners: c }); };

  return (
    <section className="scan-editor">
      <div className="scan-stage" ref={box}>
        <div className="scan-canvas" style={{ touchAction: "none" }}
          onPointerMove={(e) => { if (drag !== null) { const p = at(e); setCorners((cs) => cs.map((c, i) => (i === drag ? p : c))); } }}
          onPointerUp={() => { if (drag !== null) { setDrag(null); commit(corners); } }}>
          <canvas ref={canvas} aria-label={tr("The photo of the page")} role="img" />
          {!preview && (
            <svg className="scan-overlay" width={page.source.width * scale} height={page.source.height * scale} aria-hidden>
              <polygon points={corners.map((c) => `${c.x * scale},${c.y * scale}`).join(" ")} />
            </svg>
          )}
          {!preview && corners.map((c, i) => (
            <button key={i} className="scan-handle" style={{ left: c.x * scale, top: c.y * scale }}
              aria-label={tr("Corner {n}", { n: i + 1 })}
              onPointerDown={(e) => { (e.target as HTMLElement).setPointerCapture?.(e.pointerId); setDrag(i); }}
              onPointerMove={(e) => { if (drag === i) { const p = at(e); setCorners((cs) => cs.map((x, j) => (j === i ? p : x))); } }}
              onPointerUp={() => { setDrag(null); commit(corners); }} />
          ))}
        </div>
      </div>
      <p className="muted small">{tr("Drag the corners onto the corners of the paper.")}</p>
      <div className="admin-row">
        <button onClick={() => commit(detectCorners(page.source))}><Wand2 size={16} /> {tr("Find the page again")}</button>
        <button onClick={() => commit(fullFrame(page.source))}><Maximize size={16} /> {tr("Whole picture")}</button>
        <button onClick={() => onChange({ turns: page.turns + 1 })}><RotateCw size={16} /> {tr("Rotate")}</button>
        <label className="check"><input type="checkbox" checked={preview} onChange={(e) => setPreview(e.target.checked)} /> {tr("Show result")}</label>
      </div>
      <fieldset className="choice scan-filters">
        <legend>{tr("Look")}</legend>
        {FILTERS.map(([f, label]) => (
          <label key={f} className="check"><input type="radio" name="filter" checked={page.filter === f} onChange={() => onChange({ filter: f })} /> {tr(label)}</label>
        ))}
      </fieldset>
      <button className="primary" onClick={onDone}>{tr("Done with this page")}</button>
    </section>
  );
}
