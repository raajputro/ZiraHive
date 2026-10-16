import { useCallback, useEffect, useState } from "react";
import { RotateCcw, X } from "lucide-react";
import { api, formatBytes, type Asset } from "../api";

import { locale, t as tr } from "../i18n";
const dateFmt = new Intl.DateTimeFormat(locale(), { day: "numeric", month: "short" });

export default function TrashPage() {
  const [items, setItems] = useState<Asset[] | null>(null);
  const [error, setError] = useState("");
  const refresh = useCallback(() => { api.trash().then(setItems).catch((e) => setError(e.message)); }, []);
  useEffect(refresh, [refresh]);
  const act = async (fn: () => Promise<unknown>) => {
    try { await fn(); refresh(); } catch (e) { setError(e instanceof Error ? e.message : tr("That didn't work")); }
  };

  return (
    <div className="page">
      <header className="page-head">
        <h1>{tr("Trash")}</h1>
        {items && items.length > 0 && (
          <button className="danger" onClick={() => confirm(tr("Delete {length} files forever? This can't be undone.", { length: items.length })) && act(api.emptyTrash)}>{tr("Empty trash")}</button>
        )}
      </header>
      <p className="muted">{tr("Files stay here for 30 days, then they're deleted for good.")}</p>
      {error && <p className="error" role="alert">{error}</p>}
      {items && items.length === 0 && <div className="empty"><h2>{tr("Trash is empty")}</h2></div>}
      {items && items.length > 0 && (
        <table className="filelist">
          <thead><tr><th>{tr("Name")}</th><th className="hide-sm">{tr("From")}</th><th className="num">{tr("Size")}</th><th className="hide-sm">{tr("Deleted")}</th><th><span className="sr">{tr("Actions")}</span></th></tr></thead>
          <tbody>
            {items.map((a) => (
              <tr key={a.id}>
                <td className="fname">{a.filename}</td>
                <td className="hide-sm muted">{a.folder}</td>
                <td className="num">{formatBytes(a.size)}</td>
                <td className="hide-sm">{a.deleted_at && dateFmt.format(new Date(a.deleted_at))}</td>
                <td className="row-actions">
                  <button className="icon" title={tr("Restore")} aria-label={tr("Restore {filename}", { filename: a.filename })} onClick={() => act(() => api.restore(a.id))}><RotateCcw size={16} /></button>
                  <button className="icon" title={tr("Delete forever")} aria-label={tr("Delete {filename} forever", { filename: a.filename })}
                    onClick={() => confirm(tr("Delete \"{filename}\" forever?", { filename: a.filename })) && act(() => api.deleteForever(a.id))}><X size={16} /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
