import { useEffect, useState } from "react";
import { Download, RotateCcw } from "lucide-react";
import { api, ApiError, formatBytes, url, type Asset, type Version } from "../api";
import Dialog from "./Dialog";

import { locale, t as tr } from "../i18n";
const when = new Intl.DateTimeFormat(locale(), { dateStyle: "medium", timeStyle: "short" });

export default function VersionsDialog({ asset, onClose, onRestored }:
  { asset: Asset; onClose: () => void; onRestored: () => void }) {
  const [versions, setVersions] = useState<Version[] | null>(null);
  const [msg, setMsg] = useState("");
  const refresh = () => api.versions(asset.id).then(setVersions).catch((e) => setMsg(e.message));
  useEffect(() => { void refresh(); /* eslint-disable-next-line */ }, [asset.id]);

  const restore = async (v: Version) => {
    try { await api.restoreVersion(asset.id, v.id); setMsg(tr("Restored. The copy you replaced is kept in this list.")); await refresh(); onRestored(); }
    catch (e) { setMsg(e instanceof ApiError ? e.message : tr("Couldn't restore")); }
  };

  return (
    <Dialog title={tr("Versions of {filename}", { filename: asset.filename })} onClose={onClose}>
      <p className="muted small">{tr("Uploading a file with the same name into the same folder saves the old copy here. The last 20 are kept.")}</p>
      <ul className="rows">
        <li><div><strong>{tr("Current")}</strong><br /><span className="muted small">{when.format(new Date(asset.updated_at ?? asset.created_at))}, {formatBytes(asset.size)}</span></div></li>
        {versions?.map((v) => (
          <li key={v.id}>
            <div>{when.format(new Date(v.created_at))}<br /><span className="muted small">{formatBytes(v.size)}</span></div>
            <a className="icon" href={url.version(asset, v)} aria-label={tr("Download this version")} title={tr("Download")}><Download size={16} /></a>
            <button className="icon" onClick={() => void restore(v)} aria-label={tr("Restore this version")} title={tr("Restore")}><RotateCcw size={16} /></button>
          </li>
        ))}
      </ul>
      {versions && versions.length === 0 && <p className="muted">{tr("No older versions yet.")}</p>}
      {msg && <p role="status">{msg}</p>}
    </Dialog>
  );
}
