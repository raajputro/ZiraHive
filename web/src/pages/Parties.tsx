import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { PartyPopper } from "lucide-react";
import { api, url, type Library, type Party } from "../api";
import { WatchTabs } from "./Watch";

const when = new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });

export default function PartiesPage() {
  const [parties, setParties] = useState<Party[] | null>(null);
  const [libs, setLibs] = useState<Library[]>([]);
  const load = () => api.parties().then(setParties).catch(() => setParties([]));
  useEffect(() => { void load(); api.libraries().then(setLibs).catch(() => undefined); }, []);
  const answer = async (p: Party, rsvp: "going" | "declined") => { await api.rsvp(p.id, rsvp); void load(); };

  return (
    <div className="page cinema-page">
      <header className="page-head"><h1>Watch parties</h1></header>
      <WatchTabs libraries={libs} />
      {parties && parties.length === 0 && (
        <div className="empty">
          <h2>No watch parties yet</h2>
          <p>Open any movie or episode and press <strong>Watch together</strong>. Start now or pick a time, and invite family or friends
            who have a GharBox account.</p>
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
                  {live ? `On now, ${p.online} watching` : future ? when.format(new Date(p.scheduled_at!)) : "Ready to start"}
                  {", hosted by "}{p.is_host ? "you" : p.host}
                </span>
                <span className="muted small">
                  {p.members.map((m) => `${m.username}${m.rsvp === "going" ? " (coming)" : m.rsvp === "declined" ? " (not coming)" : ""}`).join(", ") || "Nobody invited yet"}
                </span>
              </div>
              <div className="party-actions">
                {!p.is_host && p.my_rsvp !== "going" && <button onClick={() => void answer(p, "going")}>Going</button>}
                {!p.is_host && p.my_rsvp !== "declined" && <button onClick={() => void answer(p, "declined")}>Can't make it</button>}
                <Link className={`button ${live || !future ? "primary" : ""}`} to={`/party/${p.id}`}>{live ? "Join" : "Open"}</Link>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
