import { useEffect, useState, type FormEvent } from "react";
import ZoomImage from "../components/ZoomImage";
import { Download, Folder, FileText, Film, Image, File, Play, X, ChevronLeft, ChevronRight } from "lucide-react";
import { api, ApiError, formatBytes, formatDuration, url, type PublicAsset, type PublicListing, type PublicShare } from "../api";

import HiveMark from "../components/HiveMark";
import { locale, t as tr } from "../i18n";
const icons = { photo: Image, video: Film, document: FileText, other: File };

/** What someone sees when they open a share link. No account needed. */
export default function PublicSharePage({ token }: { token: string }) {
  const [info, setInfo] = useState<PublicShare | null>(null);
  const [key, setKey] = useState<string | undefined>(() => {
    try { return sessionStorage.getItem(`zirahive:share:${token}`) ?? undefined; } catch { return undefined; }
  });
  const [listing, setListing] = useState<PublicListing | null>(null);
  const [path, setPath] = useState("/");
  const [error, setError] = useState("");
  const [password, setPassword] = useState("");
  const [open, setOpen] = useState<number | null>(null);

  useEffect(() => { document.documentElement.dataset.room = "home"; }, []);
  useEffect(() => { api.publicShare(token).then(setInfo).catch((e) => setError(e.message)); }, [token]);
  useEffect(() => {
    if (!info || (info.needs_password && !key)) return;
    api.publicItems(token, path, key).then(setListing).catch((e) => {
      if (e instanceof ApiError && e.status === 401) { setKey(undefined); return; }
      setError(e.message);
    });
  }, [info, key, path, token]);

  const unlock = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      const r = await api.unlockShare(token, password);
      try { sessionStorage.setItem(`zirahive:share:${token}`, r.key); } catch { /* private mode */ }
      setKey(r.key);
    } catch (err) { setError(err instanceof ApiError ? err.message : tr("Couldn't open the link")); }
  };

  if (error && !info) {
    return <div className="public"><div className="public-card"><h1>{tr("Link not available")}</h1><p>{error}</p></div></div>;
  }
  if (!info) return <div className="public" aria-busy="true" />;

  if (info.needs_password && !key) {
    return (
      <div className="signin">
        <form onSubmit={unlock}>
          <div className="signin-mark"><HiveMark size={56} /></div>
          <h1>{info.title}</h1>
          <p>{info.owner}{" "}{tr("shared this with a password.")}</p>
          <label>{tr("Password")}<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoFocus /></label>
          {error && <p className="error" role="alert">{error}</p>}
          <button className="primary">{tr("Open")}</button>
        </form>
      </div>
    );
  }

  const media = listing?.assets.filter((a) => a.kind === "photo" || a.kind === "video") ?? [];
  const others = listing?.assets.filter((a) => a.kind !== "photo" && a.kind !== "video") ?? [];
  const crumbs = path.split("/").filter(Boolean);

  return (
    <div className="public">
      <header className="public-head">
        <span className="brand-inline"><HiveMark size={22} />{" "}{tr("ZiraHive")}</span>
        <div>
          <h1>{info.title}</h1>
          <p className="muted">{tr("Shared by")}{" "}{info.owner}{info.expires_at ? tr(", until {date}", { date: new Date(info.expires_at).toLocaleDateString(locale()) }) : ""}</p>
        </div>
      </header>
      {info.type === "folder" && crumbs.length > 0 && (
        <nav className="crumbs small-crumbs" aria-label={tr("Folder path")}>
          <button onClick={() => setPath("/")}>{info.title}</button>
          {crumbs.map((c, i) => (
            <span key={i} className="crumb"><span className="sep" aria-hidden>/</span>
              <button onClick={() => setPath("/" + crumbs.slice(0, i + 1).join("/"))}>{c}</button></span>
          ))}
        </nav>
      )}
      {listing && (listing.folders.length > 0 || others.length > 0) && (
        <table className="filelist">
          <tbody>
            {listing.folders.map((f) => (
              <tr key={f}><td><button className="fname" onClick={() => setPath(f)}><Folder size={18} className="ico folder" /> {f.split("/").pop()}</button></td><td /></tr>
            ))}
            {others.map((a) => {
              const Icon = icons[a.kind];
              return (
                <tr key={a.id}>
                  <td><a className="fname" href={url.publicFile(token, a, key)} target="_blank" rel="noreferrer"><Icon size={18} className="ico" /> {a.filename}</a></td>
                  <td className="row-actions">
                    <span className="muted small">{formatBytes(a.size)}</span>
                    {info.allow_download && <a className="icon" href={url.publicFile(token, a, key, true)} aria-label={tr("Download {filename}", { filename: a.filename })}><Download size={16} /></a>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {media.length > 0 && (
        <div className="justified public-grid">
          {media.map((a, i) => {
            const ratio = a.width && a.height ? a.width / a.height : 1;
            return (
              <button key={a.id} className="tile" style={{ flexGrow: ratio, aspectRatio: String(ratio), ["--r" as string]: ratio }}
                onClick={() => setOpen(i)} aria-label={tr("Open {filename}", { filename: a.filename })}>
                {a.thumb_ready ? <img src={url.publicThumb(token, a, key)} alt="" loading="lazy" /> : <span className="tile-wait" />}
                {a.kind === "video" && <span className="tile-badge"><Play size={12} fill="currentColor" /> {formatDuration(a.duration)}</span>}
              </button>
            );
          })}
          <span className="justified-filler" />
        </div>
      )}
      {listing && listing.folders.length === 0 && listing.assets.length === 0 && <p className="muted">{tr("This is empty.")}</p>}
      {open !== null && media[open] && (
        <PublicViewer items={media} index={open} token={token} shareKey={key} allowDownload={info.allow_download}
          onIndex={setOpen} onClose={() => setOpen(null)} />
      )}
    </div>
  );
}

function PublicViewer({ items, index, token, shareKey, allowDownload, onIndex, onClose }:
  { items: PublicAsset[]; index: number; token: string; shareKey?: string; allowDownload: boolean;
    onIndex: (i: number) => void; onClose: () => void }) {
  const a = items[index];
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
        {allowDownload && <a className="icon" href={url.publicFile(token, a, shareKey, true)} aria-label={tr("Download")}><Download size={18} /></a>}
        <button className="icon" onClick={onClose} aria-label={tr("Close")}><X size={20} /></button>
      </div>
      {index > 0 && <button className="lb-nav prev" onClick={() => onIndex(index - 1)} aria-label={tr("Previous")}><ChevronLeft size={30} /></button>}
      <div className="lightbox-stage">
        {a.kind === "video"
          ? <video key={a.id} src={url.publicFile(token, a, shareKey)} controls autoPlay playsInline />
          : <ZoomImage key={a.id} src={url.publicPreview(token, a, shareKey)} alt={a.filename}
              onSwipe={(d) => { if (d === "next" && index < items.length - 1) onIndex(index + 1); if (d === "prev" && index > 0) onIndex(index - 1); }} />}
      </div>
      {index < items.length - 1 && <button className="lb-nav next" onClick={() => onIndex(index + 1)} aria-label={tr("Next")}><ChevronRight size={30} /></button>}
    </div>
  );
}
