import { useEffect, useState } from "react";
import { Puzzle, Send } from "lucide-react";
import { api, ApiError, type Plugin, type PluginSetting } from "../api";
import { locale, t as tr, tx } from "../i18n";

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString(locale()) : "");

export default function PluginsPanel() {
  const [list, setList] = useState<Plugin[] | null>(null);
  const load = () => api.plugins().then(setList).catch(() => setList([]));
  useEffect(() => { void load(); }, []);
  const replace = (p: Plugin) => setList((l) => l?.map((x) => (x.id === p.id ? p : x)) ?? null);

  return (
    <section className="panel plugins">
      <h2><Puzzle size={18} aria-hidden />{" "}{tr("Plugins")}</h2>
      <p className="muted">{tr("Add-ons that react to what happens in ZiraHive: new movies, uploads, backups, watch parties. Put your own in the plugins folder inside ZiraHive's data folder; see docs/PLUGINS.md.")}</p>
      {list === null ? <p aria-busy="true" className="muted">{tr("Loading…")}</p>
        : list.map((p) => <PluginCard key={p.id} plugin={p} onChange={replace} />)}
    </section>
  );
}

function PluginCard({ plugin: p, onChange }: { plugin: Plugin; onChange: (p: Plugin) => void }) {
  const [values, setValues] = useState<Record<string, unknown>>(() => Object.fromEntries(p.settings.map((s) => [s.key, s.type === "secret" ? "" : s.value ?? (s.type === "bool" ? false : "")])));
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const act = async (fn: () => Promise<void>) => {
    setMsg(""); setBusy(true);
    try { await fn(); } catch (e) { setMsg(e instanceof ApiError ? e.message : tr("That didn't work")); } finally { setBusy(false); }
  };
  const toggle = () => act(async () => {
    if (!p.enabled && !p.builtin && !confirm(tr("Turn on {name}? A plugin runs with ZiraHive's own rights and can see everyone's files. Only turn on plugins you trust.", { name: tx(p.name) }))) return;
    onChange(await api.updatePlugin(p.id, { enabled: !p.enabled }));
  });
  const save = () => act(async () => {
    const saved = await api.updatePlugin(p.id, { settings: values });
    onChange(saved);
    setValues((v) => Object.fromEntries(Object.entries(v).map(([k, x]) => [k, saved.settings.find((s) => s.key === k)?.type === "secret" ? "" : x])));
    setMsg(tr("Saved."));
  });
  const test = () => act(async () => {
    const r = await api.testPlugin(p.id);
    setMsg(r.ok ? tr("Test sent.") : tr("The test failed: {error}", { error: r.error ?? "" }));
  });

  return (
    <article className={`plugin ${p.enabled ? "on" : ""}`}>
      <header>
        <div>
          <h3>{tx(p.name)}{" "}<span className="muted small">{p.version && `v${p.version}`}</span>
            {p.builtin && <span className="tag">{tr("built in")}</span>}</h3>
          <p className="small">{tx(p.description)}</p>
        </div>
        {!p.error && (
          <label className="check switch"><input type="checkbox" checked={p.enabled} disabled={busy} onChange={() => void toggle()} />
            {p.enabled ? tr("On") : tr("Off")}</label>
        )}
      </header>
      {p.error && <p className="error">{tr("This plugin can't be used:")}{" "}{p.error}</p>}
      {p.enabled && p.last_error && (
        <p className="notice small">{tr("Last problem, {when}:", { when: when(p.last_error_at) })}{" "}<code>{p.last_error}</code></p>
      )}
      {!p.error && p.settings.length > 0 && (
        <details open={p.enabled && p.settings.some((s) => !s.has_value && s.type !== "bool")}>
          <summary>{tr("Settings")}</summary>
          <form className="stack-form" onSubmit={(e) => { e.preventDefault(); void save(); }}>
            {p.settings.map((s) => <Field key={s.key} s={s} value={values[s.key]} onChange={(v) => setValues((x) => ({ ...x, [s.key]: v }))} />)}
            <div className="admin-row">
              <button className="primary" disabled={busy}>{tr("Save settings")}</button>
              {p.enabled && <button type="button" onClick={() => void test()} disabled={busy}><Send size={15} />{" "}{tr("Send a test")}</button>}
            </div>
          </form>
        </details>
      )}
      {msg && <p role="status" className="small">{msg}</p>}
    </article>
  );
}

function Field({ s, value, onChange }: { s: PluginSetting; value: unknown; onChange: (v: unknown) => void }) {
  const help = s.help && <span className="muted small">{tx(s.help)}</span>;
  const label = tx(s.label);
  if (s.type === "bool")
    return <label className="check"><input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} /> {label}{help && <> {help}</>}</label>;
  if (s.type === "choice")
    return <label>{label}<select value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>{s.choices.map((c) => <option key={c}>{c}</option>)}</select>{help}</label>;
  return (
    <label>{label}
      <input type={s.type === "secret" ? "password" : s.type === "number" ? "number" : "text"} value={String(value ?? "")}
        placeholder={s.type === "secret" && s.has_value ? tr("Saved. Type to change it.") : undefined}
        autoComplete="off" onChange={(e) => onChange(e.target.value)} />
      {help}
    </label>
  );
}
