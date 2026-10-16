import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, type User } from "../api";
import { useAuth } from "../App";
import Dialog from "./Dialog";

import { locale, t as tr } from "../i18n";
/** Start or schedule a watch party for one movie or episode. */
export default function PartyDialog({ mediaId, title, onClose }: { mediaId: string; title: string; onClose: () => void }) {
  const { user: me } = useAuth();
  const navigate = useNavigate();
  const [people, setPeople] = useState<User[]>([]);
  const [invite, setInvite] = useState<Set<string>>(new Set());
  const [later, setLater] = useState(false);
  const [when, setWhen] = useState(() => {
    const d = new Date(Date.now() + 60 * 60 * 1000);
    d.setMinutes(0, 0, 0);
    return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  });
  const [control, setControl] = useState<"everyone" | "host">("everyone");
  const [waitForAll, setWaitForAll] = useState(true);
  const [error, setError] = useState("");
  const [done, setDone] = useState("");

  useEffect(() => { api.directory().then((all) => setPeople(all.filter((p) => p.id !== me.id))).catch(() => undefined); }, [me.id]);

  const toggle = (id: string) => setInvite((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    if (later && new Date(when).getTime() < Date.now()) { setError(tr("Pick a time in the future.")); return; }
    try {
      const party = await api.createParty({ media_id: mediaId, invite: [...invite], control, wait_for_all: waitForAll,
        scheduled_at: later ? new Date(when).toISOString() : undefined });
      if (later) setDone(tr("Invites sent for {date}. Everyone gets a reminder 10 minutes before.", { date: new Date(when).toLocaleString(locale()) }));
      else navigate(`/party/${party.id}`);
    } catch (err) { setError(err instanceof ApiError ? err.message : tr("Couldn't start the party")); }
  };

  return (
    <Dialog title={tr("Watch {title} together", { title: title })} onClose={onClose}>
      {done ? (
        <>
          <p role="status">{done}</p>
          <button className="primary" onClick={() => navigate("/watch/parties")}>{tr("See watch parties")}</button>
        </>
      ) : (
        <form className="stack-form" onSubmit={submit}>
          <fieldset className="choice">
            <legend>{tr("When")}</legend>
            <label className="check"><input type="radio" checked={!later} onChange={() => setLater(false)} />{" "}{tr("Now")}</label>
            <label className="check"><input type="radio" checked={later} onChange={() => setLater(true)} />{" "}{tr("Later")}</label>
            {later && <input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} aria-label={tr("Date and time")} required />}
          </fieldset>
          <fieldset className="choice">
            <legend>{tr("Invite")}</legend>
            {people.length === 0 && <p className="muted small">{tr("Nobody else has an account yet. Add family and friends in Settings, People.")}</p>}
            <div className="invite-grid">
              {people.map((p) => (
                <label key={p.id} className="check"><input type="checkbox" checked={invite.has(p.id)} onChange={() => toggle(p.id)} /> {p.username}</label>
              ))}
            </div>
          </fieldset>
          <label>{tr("Who can pause and skip")}<select value={control} onChange={(e) => setControl(e.target.value as "everyone" | "host")}>
              <option value="everyone">{tr("Everyone")}</option>
              <option value="host">{tr("Only me")}</option>
            </select>
          </label>
          <label className="check"><input type="checkbox" checked={waitForAll} onChange={(e) => setWaitForAll(e.target.checked)} />{tr("Pause for everyone when someone's video is loading")}</label>
          {error && <p className="error" role="alert">{error}</p>}
          <button className="primary">{later ? tr("Send invites") : tr("Start the party")}</button>
        </form>
      )}
    </Dialog>
  );
}
