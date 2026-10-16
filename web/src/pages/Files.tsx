import { useCallback, useEffect, useRef, useState, type DragEvent, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Upload, FolderPlus, Folder, FileText, Image, Film, File, Download, Pencil, Trash2, Link2, History, ShieldCheck } from "lucide-react";
import { api, url, formatBytes, type Asset, type FolderListing } from "../api";
import { useUploads } from "../uploads";
import { Lightbox } from "./Photos";
import ShareDialog from "../components/ShareDialog";
import VersionsDialog from "../components/VersionsDialog";
import type { ShareTarget } from "../api";

import { locale, t as tr } from "../i18n";
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
      {over && <div className="drop-hint">{tr("Drop to upload here")}</div>}
    </div>
  );
}

const icons = { photo: Image, video: Film, document: FileText, other: File };
const dateFmt = new Intl.DateTimeFormat(locale(), { day: "numeric", month: "short", year: "numeric" });

export default function FilesPage() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const folder = decodeURIComponent(pathname.replace(/^\/files/, "")) || "/";
  const [listing, setListing] = useState<FolderListing | null>(null);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<number | null>(null);
  const [sharing, setSharing] = useState<{ type: ShareTarget; id: string; label: string } | null>(null);
  const [versionsOf, setVersionsOf] = useState<Asset | null>(null);
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
    try { await fn(); refresh(); } catch (e) { setError(e instanceof Error ? e.message : tr("That didn't work")); }
  };
  const newFolder = () => {
    const name = prompt(tr("New folder name"));
    if (name?.trim()) void act(() => api.createFolder(`${folder}/${name.trim()}`));
  };
  const rename = (a: Asset) => {
    const name = prompt(tr("Rename file"), a.filename);
    if (name?.trim() && name !== a.filename) void act(() => api.updateAsset(a.id, { filename: name.trim() }));
  };
  const viewable = listing?.assets.filter((a) => a.kind === "photo" || a.kind === "video") ?? [];

  return (
    <DropZone onFiles={(files) => enqueue(files, folder, { dedupe: false })}>
      <div className="page">
        <header className="page-head">
          <nav className="crumbs" aria-label={tr("Folder path")}>
            <button onClick={() => go("/")} className={crumbs.length ? "" : "here"}>{tr("My files")}</button>
            {crumbs.map((c, i) => {
              const path = "/" + crumbs.slice(0, i + 1).join("/");
              return <span key={path} className="crumb"><span className="sep" aria-hidden>/</span><button onClick={() => go(path)} className={i === crumbs.length - 1 ? "here" : ""}>{c}</button></span>;
            })}
          </nav>
          {folder !== "/" && (
            <button onClick={() => setSharing({ type: "folder", id: folder, label: folder.split("/").pop()! })}><Link2 size={17} />{" "}{tr("Share folder")}</button>
          )}
          <Link to="/vault" className="button"><ShieldCheck size={17} />{" "}{tr("Vault")}</Link>
          <button onClick={newFolder}><FolderPlus size={17} />{" "}{tr("New folder")}</button>
          <button className="primary" onClick={() => input.current?.click()}><Upload size={17} />{" "}{tr("Upload")}</button>
          <input ref={input} type="file" multiple hidden
            onChange={(e) => { enqueue(Array.from(e.target.files ?? []), folder, { dedupe: false }); e.target.value = ""; }} />
        </header>
        {error && <p className="error" role="alert">{error}</p>}
        {listing && listing.folders.length === 0 && listing.assets.length === 0 && (
          <div className="empty">
            <h2>{folder === "/" ? tr("Nothing backed up yet") : tr("This folder is empty")}</h2>
            <p>{tr("Drag files here or use Upload. Documents, photos and anything else you want to keep are welcome.")}</p>
          </div>
        )}
        {listing && (listing.folders.length > 0 || listing.assets.length > 0) && (
          <table className="filelist">
            <thead><tr><th>{tr("Name")}</th><th className="num">{tr("Size")}</th><th className="hide-sm">{tr("Modified")}</th><th><span className="sr">{tr("Actions")}</span></th></tr></thead>
            <tbody>
              {listing.folders.map((f) => (
                <tr key={f}>
                  <td><Link className="fname" to={`/files${f.split("/").map(encodeURIComponent).join("/")}`}><Folder size={18} className="ico folder" /> {f.split("/").pop()}</Link></td>
                  <td className="num">—</td><td className="hide-sm" />
                  <td className="row-actions">
                    <button className="icon" aria-label={tr("Share folder {f}", { f: f })} title={tr("Share")}
                      onClick={() => setSharing({ type: "folder", id: f, label: f.split("/").pop()! })}><Link2 size={16} /></button>
                    <button className="icon" aria-label={tr("Delete folder {f}", { f: f })} title={tr("Move folder to trash")}
                      onClick={() => confirm(tr("Move \"{pop}\" and everything in it to the trash?", { pop: f.split("/").pop() })) && act(() => api.deleteFolder(f))}><Trash2 size={16} /></button>
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
                    <td className="hide-sm">{dateFmt.format(new Date(a.updated_at ?? a.created_at))}</td>
                    <td className="row-actions">
                      <button className="icon" onClick={() => setSharing({ type: "asset", id: a.id, label: a.filename })}
                        aria-label={tr("Share {filename}", { filename: a.filename })} title={tr("Share")}><Link2 size={16} /></button>
                      {(a.kind === "document" || a.kind === "other") && (
                        <button className="icon" onClick={() => setVersionsOf(a)} aria-label={tr("Versions of {filename}", { filename: a.filename })} title={tr("Versions")}><History size={16} /></button>
                      )}
                      <a className="icon" href={url.file(a, true)} aria-label={tr("Download {filename}", { filename: a.filename })} title={tr("Download")}><Download size={16} /></a>
                      <button className="icon" onClick={() => rename(a)} aria-label={tr("Rename {filename}", { filename: a.filename })} title={tr("Rename")}><Pencil size={16} /></button>
                      <button className="icon" onClick={() => act(() => api.trashAsset(a.id))} aria-label={tr("Move {filename} to trash", { filename: a.filename })} title={tr("Move to trash")}><Trash2 size={16} /></button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
      {preview !== null && <Lightbox items={viewable} index={preview} onIndex={setPreview} onClose={() => setPreview(null)} />}
      {sharing && <ShareDialog {...sharing} onClose={() => setSharing(null)} />}
      {versionsOf && <VersionsDialog asset={versionsOf} onClose={() => setVersionsOf(null)} onRestored={refresh} />}
    </DropZone>
  );
}
