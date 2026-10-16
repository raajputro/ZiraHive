import { useEffect, useState, type FormEvent } from "react";
import { Copy, Trash2, Check } from "lucide-react";
import { api, ApiError, url, type Share, type ShareTarget } from "../api";
import Dialog from "./Dialog";

const dateFmt = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", year: "numeric" });

/** Make a link for a file, folder or album, and manage the links that already exist for it. */
export default function ShareDialog({ type, id, label, onClose }:
  { type: ShareTarget; id: string; label: string; onClose: () => void }) {
  const [links, setLinks] = useState<Share[]>([]);
  const [password, setPassword] = useState("");
  const [expires, setExpires] = useState("7");
  const [download, setDownload] = useState(true);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState("");

  const refresh = () => api.shares().then((all) => setLinks(all.filter((s) => s.target_type === type && s.target_id === id)));
  useEffect(() => { void refresh(); /* eslint-disable-next-line */ }, [type, id]);

  const copy = async (s: Share) => {
    try { await navigator.clipboard.writeText(url.shareLink(s)); setCopied(s.id); setTimeout(() => setCopied(""), 2000); }
    catch { setError("Copy didn't work here. Select the link and copy it by hand."); }
  };
  const create = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      const s = await api.createShare({ target_type: type, target_id: id, password: password || undefined,
        expires_days: expires ? Number(expires) : undefined, allow_download: download });
      setPassword("");
      await refresh();
      void copy(s);
    } catch (err) { setError(err instanceof ApiError ? err.message : "Couldn't make the link"); }
  };
  const remove = async (s: Share) => { await api.deleteShare(s.id); await refresh(); };

  return (
    <Dialog title={`Share ${label}`} onClose={onClose}>
      <p className="muted small">Anyone with the link can open it, even without a GharBox account.</p>
      {links.length > 0 && (
        <ul className="share-list">
          {links.map((s) => (
            <li key={s.id}>
              <input readOnly value={url.shareLink(s)} onFocus={(e) => e.currentTarget.select()} aria-label="Share link" />
              <button className="icon" onClick={() => void copy(s)} aria-label="Copy link" title="Copy link">
                {copied === s.id ? <Check size={16} /> : <Copy size={16} />}
              </button>
              <button className="icon" onClick={() => void remove(s)} aria-label="Delete link" title="Delete link"><Trash2 size={16} /></button>
              <span className="muted small">
                {[s.has_password ? "password" : "no password",
                  s.expires_at ? `expires ${dateFmt.format(new Date(s.expires_at))}` : "never expires",
                  s.allow_download ? null : "view only", `${s.views} views`].filter(Boolean).join(", ")}
              </span>
            </li>
          ))}
        </ul>
      )}
      <form className="stack-form" onSubmit={create}>
        <label>Password (optional)
          <input type="text" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="off" placeholder="Leave empty for no password" />
        </label>
        <label>Link stops working
          <select value={expires} onChange={(e) => setExpires(e.target.value)}>
            <option value="1">after 1 day</option>
            <option value="7">after 7 days</option>
            <option value="30">after 30 days</option>
            <option value="365">after a year</option>
            <option value="">never</option>
          </select>
        </label>
        <label className="check"><input type="checkbox" checked={download} onChange={(e) => setDownload(e.target.checked)} /> Allow downloads</label>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="primary">Create and copy link</button>
      </form>
    </Dialog>
  );
}
