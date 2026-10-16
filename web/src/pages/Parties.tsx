import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { PartyPopper } from "lucide-react";
import { api, url, type Library, type Party } from "../api";
import { WatchTabs } from "./Watch";

import { locale, t as tr } from "../i18n";
const when = new Intl.DateTimeFormat(locale(), { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });

export default function PartiesPage() {
  const [parties, setParties] = useState<Party[] | null>(null);
  const [libs, setLibs] = useState<Library[]>([]);
  const load = () => api.parties().then(setParties).catch(() => setParties([]));
  useEffect(() => { void load(); api.libraries().then(setLibs).catch(() => undefined); }, []);
  const answer = async (p: Party, rsvp: "going" | "declined") => { await api.rsvp(p.id, rsvp); void load(); };

  return (
    <div className="page cinema-page">
      <header className="page-head"><h1>{tr("Watch parties")}</h1></header>
      <WatchTabs libraries={libs} />
      {parties && parties.length === 0 && (
        <div className="empty">
          <h2>{tr("No watch parties yet")}</h2>
          <p>{tr("Open any movie or episode and press")}{" "}<strong>{tr("Watch together")}</strong>{tr(". Start now or pick a time, and invite family or friends who have a GharBox account.")}</p>
        </div>
      )}
      <ul className="party-list">
        {parties?.map((p) => {
          const live = p.online > 0;
          const future = p.scheduled_at && new Date(p.scheduled_at).getTime() > Date.now();
          return (
            <li key={p.id} className="party-card">
              <div className="party-art">{p.poster_ready ? <img src={url.poster({ id: p.media_id })} alt="" /> : <PartyPopper size={28} />}</div>
              <div className="party-text">
                <strong>{p.title}</strong>
                <span className="muted small">
                  {live ? tr("On now, {online} watching", { online: p.online }) : future ? when.format(new Date(p.scheduled_at!)) : tr("Ready to start")}
                  {p.is_host ? tr(", hosted by you") : tr(", hosted by {name}", { name: p.host })}
                </span>
                <span className="muted small">
                  {p.members.map((m) => `${m.username}${m.rsvp === "going" ? tr(" (coming)") : m.rsvp === "declined" ? tr(" (not coming)") : ""}`).join(", ") || tr("Nobody invited yet")}
                </span>
              </div>
              <div className="party-actions">
                {!p.is_host && p.my_rsvp !== "going" && <button onClick={() => void answer(p, "going")}>{tr("Going")}</button>}
                {!p.is_host && p.my_rsvp !== "declined" && <button onClick={() => void answer(p, "declined")}>{tr("Can't make it")}</button>}
                <Link className={`button ${live || !future ? "primary" : ""}`} to={`/party/${p.id}`}>{live ? tr("Join") : tr("Open")}</Link>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
