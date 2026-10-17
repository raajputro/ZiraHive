import { useEffect, useState } from "react";
import { Copy, Link2, Trash2 } from "lucide-react";
import { api, ApiError, AGE_LABEL, AGE_OPTIONS, publicAddress, VIDEO_KINDS, type Library, type LinkGuest, type LinkedServer } from "../api";
import Dialog from "./Dialog";
import { locale, t as tr } from "../i18n";

const day = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString(locale()) : tr("not yet"));

/** Settings > Server > Linked GharBox servers: share with another GharBox, or watch one. */
export default function LinksPanel() {
  const [libs, setLibs] = useState<Library[]>([]);
  const [guests, setGuests] = useState<LinkGuest[]>([]);
  const [links, setLinks] = useState<LinkedServer[]>([]);
  const [name, setName] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);
  const [age, setAge] = useState<string>("");
  const [address, setAddress] = useState(() => publicAddress() || location.origin);
  const [code, setCode] = useState<{ name: string; code: string } | null>(null);
  const [paste, setPaste] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => {
    api.linkGuests().then(setGuests).catch(() => undefined);
    api.links().then(setLinks).catch(() => undefined);
  };
  useEffect(() => {
    api.libraries().then((all) => setLibs(all.filter((l) => VIDEO_KINDS.includes(l.kind)))).catch(() => undefined);
    load();
  }, []);

  const act = async (fn: () => Promise<void>) => {
    setMsg(""); setBusy(true);
    try { await fn(); } catch (e) { setMsg(e instanceof ApiError ? e.message : tr("That didn't work")); } finally { setBusy(false); }
  };
  const invite = () => act(async () => {
    const g = await api.createLinkGuest({ name: name.trim(), library_ids: chosen, max_age: age === "" ? null : Number(age), url: address.trim() });
    setCode({ name: g.name, code: g.code ?? "" });
    setName(""); setChosen([]);
    load();
  });
  const add = () => act(async () => {
    const l = await api.addLink(paste.trim());
    setPaste("");
    setMsg(tr("Linked with {name}. Its categories are now on the Watch page.", { name: l.name }));
    load();
  });
  const libName = (id: string) => libs.find((l) => l.id === id)?.name ?? "?";

  return (
    <section className="panel links-panel">
      <h2><Link2 size={18} aria-hidden />{" "}{tr("Linked GharBox servers")}</h2>
      <p className="muted">{tr("Share some of your movie and series categories with family or friends who have their own GharBox, and watch theirs. Their server fetches for their people, so nobody gets an account here, and you choose exactly which categories they see.")}</p>

      <h3>{tr("Share with another GharBox")}</h3>
      {guests.length > 0 && (
        <ul className="link-list">
          {guests.map((g) => (
            <li key={g.id}>
              <div>
                <strong>{g.name}</strong>
                <span className="muted small">
                  {g.library_ids.map(libName).join(", ")}{g.max_age != null ? ` · ${AGE_LABEL[g.max_age]}` : ""}
                  {" · "}{tr("last visit {when}", { when: day(g.last_seen_at) })}
                </span>
              </div>
              <button className="icon" disabled={busy} aria-label={tr("Stop sharing with {name}", { name: g.name })}
                onClick={() => { if (confirm(tr("Stop sharing with {name}? Their GharBox loses access straight away.", { name: g.name }))) void act(async () => { await api.removeLinkGuest(g.id); load(); }); }}>
                <Trash2 size={16} /></button>
            </li>
          ))}
        </ul>
      )}
      <form className="stack-form" onSubmit={(e) => { e.preventDefault(); void invite(); }}>
        <label>{tr("Who is it for?")}<input value={name} onChange={(e) => setName(e.target.value)} placeholder={tr("For example: Rahim's house")} maxLength={100} required /></label>
        <fieldset className="choice">
          <legend>{tr("Categories to share")}</legend>
          {libs.length === 0 && <p className="muted small">{tr("Add movie or series categories first.")}</p>}
          {libs.map((l) => (
            <label key={l.id} className="check">
              <input type="checkbox" checked={chosen.includes(l.id)}
                onChange={(e) => setChosen((c) => (e.target.checked ? [...c, l.id] : c.filter((x) => x !== l.id)))} /> {l.name}
            </label>
          ))}
        </fieldset>
        <label>{tr("Age limit")}
          <select value={age} onChange={(e) => setAge(e.target.value)}>
            <option value="">{tr("No limit")}</option>
            {AGE_OPTIONS.filter((a) => a > 0).map((a) => <option key={a} value={a}>{tr("Only rated {age} or younger", { age: AGE_LABEL[a] })}</option>)}
          </select>
        </label>
        <label>{tr("This GharBox's address, as their server reaches it")}
          <input value={address} onChange={(e) => setAddress(e.target.value)} required />
          <span className="muted small">{tr("Use your public share address (https://…ts.net:8443) when they are elsewhere, or your Tailscale address if their server is on your Tailscale.")}</span>
        </label>
        <button className="primary" disabled={busy || chosen.length === 0 || !name.trim()}>{tr("Make a link code")}</button>
      </form>

      <h3>{tr("Watch another GharBox")}</h3>
      {links.length > 0 && (
        <ul className="link-list">
          {links.map((l) => (
            <li key={l.id}>
              <div>
                <strong>{l.name}</strong>
                <span className={`small ${l.ok ? "muted" : "error"}`}>
                  {l.ok ? l.libraries.map((x) => x.name).join(", ") || tr("nothing shared yet") : (l.last_error ?? tr("can't be reached right now"))}
                </span>
              </div>
              <button className="icon" disabled={busy} aria-label={tr("Remove {name}", { name: l.name })}
                onClick={() => { if (confirm(tr("Remove {name}? Its titles disappear from Watch here.", { name: l.name }))) void act(async () => { await api.removeLink(l.id); load(); }); }}>
                <Trash2 size={16} /></button>
            </li>
          ))}
        </ul>
      )}
      <form className="inline-form" onSubmit={(e) => { e.preventDefault(); void add(); }}>
        <label>{tr("Link code from the other GharBox")}<input value={paste} onChange={(e) => setPaste(e.target.value)} placeholder="ghx1.…" required /></label>
        <button className="primary" disabled={busy}>{tr("Link")}</button>
      </form>
      {msg && <p role="status">{msg}</p>}

      {code && (
        <Dialog title={tr("Link code for {name}", { name: code.name })} onClose={() => setCode(null)}>
          <p>{tr("Send this code to the admin of their GharBox, privately (it works like a key). They paste it in Settings > Server > Linked GharBox servers. It's shown only once.")}</p>
          <textarea className="link-code" readOnly value={code.code} rows={4} onFocus={(e) => e.target.select()} aria-label={tr("Link code")} />
          <button className="primary" onClick={() => void navigator.clipboard?.writeText(code.code)}><Copy size={16} />{" "}{tr("Copy code")}</button>
        </Dialog>
      )}
    </section>
  );
}
