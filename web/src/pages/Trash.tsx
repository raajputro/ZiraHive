import { useCallback, useEffect, useState } from "react";
import { RotateCcw, X } from "lucide-react";
import { api, formatBytes, type Asset } from "../api";

const dateFmt = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" });

export default function TrashPage() {
  const [items, setItems] = useState<Asset[] | null>(null);
  const [error, setError] = useState("");
  const refresh = useCallback(() => { api.trash().then(setItems).catch((e) => setError(e.message)); }, []);
  useEffect(refresh, [refresh]);
  const act = async (fn: () => Promise<unknown>) => {
    try { await fn(); refresh(); } catch (e) { setError(e instanceof Error ? e.message : "That didn't work"); }
  };

  return (
    <div className="page">
      <header className="page-head">
        <h1>Trash</h1>
        {items && items.length > 0 && (
          <button className="danger" onClick={() => confirm(`Delete ${items.length} files forever? This can't be undone.`) && act(api.emptyTrash)}>Empty trash</button>
        )}
      </header>
      <p className="muted">Files stay here for 30 days, then they're deleted for good.</p>
      {error && <p className="error" role="alert">{error}</p>}
      {items && items.length === 0 && <div className="empty"><h2>Trash is empty</h2></div>}
      {items && items.length > 0 && (
        <table className="filelist">
          <thead><tr><th>Name</th><th className="hide-sm">From</th><th className="num">Size</th><th className="hide-sm">Deleted</th><th><span className="sr">Actions</span></th></tr></thead>
          <tbody>
            {items.map((a) => (
              <tr key={a.id}>
                <td className="fname">{a.filename}</td>
                <td className="hide-sm muted">{a.folder}</td>
                <td className="num">{formatBytes(a.size)}</td>
                <td className="hide-sm">{a.deleted_at && dateFmt.format(new Date(a.deleted_at))}</td>
                <td className="row-actions">
                  <button className="icon" title="Restore" aria-label={`Restore ${a.filename}`} onClick={() => act(() => api.restore(a.id))}><RotateCcw size={16} /></button>
                  <button className="icon" title="Delete forever" aria-label={`Delete ${a.filename} forever`}
                    onClick={() => confirm(`Delete "${a.filename}" forever?`) && act(() => api.deleteForever(a.id))}><X size={16} /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
