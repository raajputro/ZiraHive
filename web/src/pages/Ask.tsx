// Ask your files: a question in plain Bangla or English, answered from your own documents by the
// local language model, with the passages it used.
import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, FileText, Sparkles } from "lucide-react";
import { api, ApiError, type AskAnswer } from "../api";
import { num, t as tr } from "../i18n";

interface Turn { q: string; a?: AskAnswer; error?: string }

export default function AskPage() {
  const [q, setQ] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState<{ on: boolean; docs: number } | null>(null);
  useEffect(() => { api.aiStatus().then((s) => setReady({ on: s.ollama, docs: s.documents_ready })).catch(() => undefined); }, []);

  const ask = async (e: FormEvent) => {
    e.preventDefault();
    const question = q.trim();
    if (!question) return;
    setQ(""); setBusy(true);
    setTurns((t) => [...t, { q: question }]);
    try {
      const a = await api.ask(question);
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, a } : x)));
    } catch (err) {
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, error: err instanceof ApiError ? err.message : tr("That didn't work") } : x)));
    } finally { setBusy(false); }
  };

  return (
    <div className="page ask-page">
      <Link to="/files" className="back"><ArrowLeft size={18} />{" "}{tr("Files")}</Link>
      <header className="page-head"><h1><Sparkles size={22} aria-hidden />{" "}{tr("Ask your files")}</h1></header>
      <p className="muted">{tr("Ask in Bangla or English, for example \"When does my passport expire?\" or \"How much was the electricity bill in May?\". The answer comes from your own documents, on this PC, and shows where it was found.")}</p>
      {ready && !ready.on && <p className="notice">{tr("This needs the local AI, which isn't running. An admin can start it; see docs/AI.md.")}</p>}
      {ready?.on && <p className="muted small">{tr("{n} documents are ready to answer from.", { n: num(ready.docs) })}</p>}
      <ol className="ask-turns">
        {turns.map((t, i) => (
          <li key={i}>
            <p className="ask-q">{t.q}</p>
            {t.error && <p className="error">{t.error}</p>}
            {!t.a && !t.error && <p className="muted" aria-busy="true">{tr("Reading your files…")}</p>}
            {t.a && (
              <div className="ask-a">
                <p>{t.a.answer}</p>
                {t.a.sources.length > 0 && (
                  <details>
                    <summary>{tr("Found in {n} places", { n: num(t.a.sources.length) })}</summary>
                    <ul className="ask-sources">
                      {t.a.sources.map((s) => (
                        <li key={s.n}>
                          <Link to={`/files${s.folder === "/" ? "" : s.folder.split("/").map(encodeURIComponent).join("/")}`}>
                            <FileText size={14} aria-hidden />{" "}[{num(s.n)}] {s.filename}
                          </Link>
                          <blockquote className="small">{s.passage.length > 400 ? s.passage.slice(0, 400) + "…" : s.passage}</blockquote>
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </div>
            )}
          </li>
        ))}
      </ol>
      <form className="ask-form" onSubmit={ask}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={tr("Ask about your documents…")} aria-label={tr("Your question")} maxLength={1000} />
        <button className="primary" disabled={busy || !q.trim()}>{tr("Ask")}</button>
      </form>
    </div>
  );
}
