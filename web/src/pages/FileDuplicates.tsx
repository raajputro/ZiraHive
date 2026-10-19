// Duplicate documents in Files: exact copies and edited versions, newest kept. Removed files go
// to the trash for 30 days.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Check } from "lucide-react";
import { api, url, type DocDuplicates } from "../api";
import { locale, t as tr } from "../i18n";
import DuplicateDocs, { type DocGroup } from "../components/DuplicateDocs";

const num = (n: number) => n.toLocaleString(locale());

export default function FileDuplicatesPage() {
  const [data, setData] = useState<DocDuplicates | null>(null);
  const [gone, setGone] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { api.fileDuplicates().then(setData).catch((e) => setError(e.message)); }, []);
  const trash = async (ids: string[]) => {
    setBusy(true);
    try { for (const id of ids) { await api.trashAsset(id); setGone((g) => new Set([...g, id])); } }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };

  const groups: DocGroup[] = (data?.groups ?? []).map((g) => ({
    keep: g.keep, same: g.same, similarity: g.similarity,
    files: g.files.filter((f) => !gone.has(f.id)).map((f) => ({ id: f.id, name: f.filename, folder: f.folder, size: f.size, date: f.updated_at ?? f.created_at })),
  })).filter((g) => g.files.length > 1 && g.files.some((f) => f.id === g.keep));

  return (
    <div className="page cleanup">
      <header className="page-head">
        <Link to="/files" className="button"><ArrowLeft size={17} />{" "}{tr("Files")}</Link>
        <h1>{tr("Duplicate documents")}</h1>
      </header>
      {error && <p className="error" role="alert">{error}</p>}
      {!data ? <p className="muted" aria-busy="true">{tr("Comparing your documents...")}</p> : (
        <section>
          <p className="muted small">{tr("Copies of the same document, and edited versions of it (most of the words the same). The newest is marked Keep. Removed files go to the trash for 30 days.")}</p>
          {data.waiting > 0 && <p className="notice small">{tr("{n} documents are still being read. Come back later for them.", { n: num(data.waiting) })}</p>}
          {groups.length === 0 ? <p className="muted"><Check size={16} aria-hidden />{" "}{tr("No duplicate documents.")}</p> : (
            <DuplicateDocs groups={groups} busy={busy} onRemove={(ids) => void trash(ids)}
              removeAllLabel={(n) => tr("Keep the newest of each, remove {n}", { n: num(n) })}
              open={(f) => url.view({ id: f.id })} />
          )}
          <p className="muted small">{tr("Checked {n} documents.", { n: num(data.checked) })}</p>
        </section>
      )}
    </div>
  );
}
