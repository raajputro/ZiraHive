import { useEffect, useState } from "react";
import { Sparkles } from "lucide-react";
import { api, type AiStatus } from "../api";
import { num, t as tr } from "../i18n";

/** Settings > Server > Local AI: what's running, how far indexing is, and a catch-up button. */
export default function AiPanel() {
  const [s, setS] = useState<AiStatus | null>(null);
  const [msg, setMsg] = useState("");
  useEffect(() => { api.aiStatus().then(setS).catch(() => undefined); }, []);
  if (!s) return null;
  const on = (x: boolean) => <span className={x ? "ok-text" : "muted"}>{x ? tr("running") : tr("not running")}</span>;
  return (
    <section className="panel">
      <h2><Sparkles size={18} aria-hidden />{" "}{tr("Local AI")}</h2>
      <p className="muted">{tr("Search photos by what's in them, group faces, make subtitles and answer questions about your documents, all on this PC with free models. Start it with: docker compose --profile ai up -d")}</p>
      <ul className="plain-list">
        <li>{tr("Pictures, faces and subtitles")}: {on(s.ai)}</li>
        <li>{tr("Questions (Ollama, {model})", { model: s.llm_model })}: {on(s.ollama)}</li>
        {s.ai && <li>{tr("Your photos looked at: {done} of {total}", { done: num(s.photos_indexed), total: num(s.photos) })}</li>}
        {s.ai && <li>{tr("People found: {n}", { n: num(s.people) })}</li>}
        {s.ollama && <li>{tr("Your documents ready for questions: {n}", { n: num(s.documents_ready) })}</li>}
      </ul>
      {(s.ai || s.ollama) && (
        <button onClick={async () => { await api.aiCatchUp(); setMsg(tr("Started. It continues in the background; this can take hours the first time.")); }}>
          {tr("Catch up now")}
        </button>
      )}
      {msg && <p role="status" className="small">{msg}</p>}
      <p className="muted small">{tr("The first use downloads the models once (about 700 MB for pictures and speech, 2 to 3 GB for questions). Everything stays on this PC.")}</p>
    </section>
  );
}
