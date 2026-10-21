// Groups of duplicate documents (exact copies or edited versions), one row per file, with the one
// to keep marked. Used by Files (server-side matching) and the vault (matching done in the browser).
import { FileText, Trash2 } from "lucide-react";
import { formatBytes } from "../api";
import { locale, t as tr } from "../i18n";

export interface DocRow { id: string; name: string; folder: string; size: number; date: string | number | null }
export interface DocGroup { keep: string; same: boolean; similarity: number; files: DocRow[] }

const dateFmt = new Intl.DateTimeFormat(locale(), { day: "numeric", month: "short", year: "numeric" });
const num = (n: number) => n.toLocaleString(locale());

export default function DuplicateDocs({ groups, busy, onRemove, removeAllLabel, open }: {
  groups: DocGroup[];
  busy: boolean;
  onRemove: (ids: string[]) => void;
  removeAllLabel: (n: number) => string;
  open?: (row: DocRow) => string | undefined;  // a link to look at the file, when there is one
}) {
  const extra = groups.flatMap((g) => g.files.filter((f) => f.id !== g.keep).map((f) => f.id));
  if (!groups.length) return null;
  return (
    <>
      <button className="primary" disabled={busy} onClick={() => onRemove(extra)}><Trash2 size={16} />{" "}{removeAllLabel(extra.length)}</button>
      {groups.map((g) => (
        <div key={g.keep} className="doc-dupes">
          <p className="muted small doc-dupes-head">
            {g.same ? tr("Exact copies") : tr("Edited versions: {pct}% of the words are the same", { pct: num(Math.round(g.similarity * 100)) })}
          </p>
          <ul>
            {g.files.map((f) => {
              const href = open?.(f);
              return (
                <li key={f.id} className={f.id === g.keep ? "keep" : ""}>
                  <FileText size={18} aria-hidden className="ico" />
                  <span className="doc-dupes-name">
                    {href ? <a href={href} target="_blank" rel="noreferrer">{f.name}</a> : f.name}
                    <span className="muted small">{f.folder}</span>
                  </span>
                  <span className="muted small num">{formatBytes(f.size)}</span>
                  <span className="muted small hide-sm">{f.date ? dateFmt.format(new Date(f.date)) : ""}</span>
                  {f.id === g.keep ? <span className="tag">{tr("Keep")}</span>
                    : <button className="link-button" disabled={busy} onClick={() => onRemove([f.id])}>{tr("Remove")}</button>}
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </>
  );
}
