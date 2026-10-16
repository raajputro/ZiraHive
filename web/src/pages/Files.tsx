import { useCallback, useEffect, useRef, useState, type DragEvent, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Upload, FolderPlus, Folder, FileText, Image, Film, File, Download, Pencil, Trash2 } from "lucide-react";
import { api, url, formatBytes, type Asset, type FolderListing } from "../api";
import { useUploads } from "../uploads";
import { Lightbox } from "./Photos";

export function DropZone({ onFiles, children }: { onFiles: (f: File[]) => void; children: ReactNode }) {
  const [over, setOver] = useState(false);
  const depth = useRef(0);
  const has = (e: DragEvent) => e.dataTransfer.types.includes("Files");
  return (
    <div className={`dropzone ${over ? "over" : ""}`}
      onDragEnter={(e) => { if (has(e)) { depth.current++; setOver(true); } }}
      onDragLeave={() => { if (--depth.current <= 0) { depth.current = 0; setOver(false); } }}
      onDragOver={(e) => { if (has(e)) e.preventDefault(); }}
      onDrop={(e) => { e.preventDefault(); depth.current = 0; setOver(false); onFiles(Array.from(e.dataTransfer.files)); }}>
      {children}
      {over && <div className="drop-hint">Drop to upload here</div>}
    </div>
  );
}

const icons = { photo: Image, video: Film, document: FileText, other: File };
const dateFmt = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", year: "numeric" });

export default function FilesPage() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const folder = decodeURIComponent(pathname.replace(/^\/files/, "")) || "/";
  const [listing, setListing] = useState<FolderListing | null>(null);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<number | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const { enqueue, onComplete } = useUploads();

  const refresh = useCallback(() => {
    api.files(folder).then((l) => { setListing(l); setError(""); })
      .catch((e) => setError(e.message));
  }, [folder]);
  useEffect(refresh, [refresh]);
  useEffect(() => onComplete(refresh), [onComplete, refresh]);

  const crumbs = folder.split("/").filter(Boolean);
  const go = (path: string) => navigate(`/files${path === "/" ? "" : path.split("/").map(encodeURIComponent).join("/")}`);

  const act = async (fn: () => Promise<unknown>) => {
    try { await fn(); refresh(); } catch (e) { setError(e instanceof Error ? e.message : "That didn't work"); }
  };
  const newFolder = () => {
    const name = prompt("New folder name");
    if (name?.trim()) void act(() => api.createFolder(`${folder}/${name.trim()}`));
  };
  const rename = (a: Asset) => {
    const name = prompt("Rename file", a.filename);
    if (name?.trim() && name !== a.filename) void act(() => api.updateAsset(a.id, { filename: name.trim() }));
  };
  const viewable = listing?.assets.filter((a) => a.kind === "photo" || a.kind === "video") ?? [];

  return (
    <DropZone onFiles={(files) => enqueue(files, folder)}>
      <div className="page">
        <header className="page-head">
          <nav className="crumbs" aria-label="Folder path">
            <button onClick={() => go("/")} className={crumbs.length ? "" : "here"}>My files</button>
            {crumbs.map((c, i) => {
              const path = "/" + crumbs.slice(0, i + 1).join("/");
              return <span key={path} className="crumb"><span className="sep" aria-hidden>/</span><button onClick={() => go(path)} className={i === crumbs.length - 1 ? "here" : ""}>{c}</button></span>;
            })}
          </nav>
          <button onClick={newFolder}><FolderPlus size={17} /> New folder</button>
          <button className="primary" onClick={() => input.current?.click()}><Upload size={17} /> Upload</button>
          <input ref={input} type="file" multiple hidden
            onChange={(e) => { enqueue(Array.from(e.target.files ?? []), folder); e.target.value = ""; }} />
        </header>
        {error && <p className="error" role="alert">{error}</p>}
        {listing && listing.folders.length === 0 && listing.assets.length === 0 && (
          <div className="empty">
            <h2>{folder === "/" ? "Nothing backed up yet" : "This folder is empty"}</h2>
            <p>Drag files here or use Upload. Documents, photos and anything else you want to keep are welcome.</p>
          </div>
        )}
        {listing && (listing.folders.length > 0 || listing.assets.length > 0) && (
          <table className="filelist">
            <thead><tr><th>Name</th><th className="num">Size</th><th className="hide-sm">Added</th><th><span className="sr">Actions</span></th></tr></thead>
            <tbody>
              {listing.folders.map((f) => (
                <tr key={f}>
                  <td><Link className="fname" to={`/files${f.split("/").map(encodeURIComponent).join("/")}`}><Folder size={18} className="ico folder" /> {f.split("/").pop()}</Link></td>
                  <td className="num">—</td><td className="hide-sm" />
                  <td className="row-actions">
                    <button className="icon" aria-label={`Delete folder ${f}`} title="Move folder to trash"
                      onClick={() => confirm(`Move "${f.split("/").pop()}" and everything in it to the trash?`) && act(() => api.deleteFolder(f))}><Trash2 size={16} /></button>
                  </td>
                </tr>
              ))}
              {listing.assets.map((a) => {
                const Icon = icons[a.kind];
                const vi = viewable.indexOf(a);
                return (
                  <tr key={a.id}>
                    <td>
                      {vi >= 0
                        ? <button className="fname" onClick={() => setPreview(vi)}>{a.thumb_ready ? <img src={url.thumb(a)} alt="" className="mini" /> : <Icon size={18} className="ico" />} {a.filename}</button>
                        : <a className="fname" href={url.file(a)} target="_blank" rel="noreferrer"><Icon size={18} className="ico" /> {a.filename}</a>}
                    </td>
                    <td className="num">{formatBytes(a.size)}</td>
                    <td className="hide-sm">{dateFmt.format(new Date(a.created_at))}</td>
                    <td className="row-actions">
                      <a className="icon" href={url.file(a, true)} aria-label={`Download ${a.filename}`} title="Download"><Download size={16} /></a>
                      <button className="icon" onClick={() => rename(a)} aria-label={`Rename ${a.filename}`} title="Rename"><Pencil size={16} /></button>
                      <button className="icon" onClick={() => act(() => api.trashAsset(a.id))} aria-label={`Move ${a.filename} to trash`} title="Move to trash"><Trash2 size={16} /></button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
      {preview !== null && <Lightbox items={viewable} index={preview} onIndex={setPreview} onClose={() => setPreview(null)} />}
    </DropZone>
  );
}
