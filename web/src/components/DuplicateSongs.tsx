// Settings → Server: songs the duplicate check took out of Listen, with "keep both" to undo.
import { useEffect, useState } from "react";
import { CopyX } from "lucide-react";
import { api, formatBytes, type DuplicateSong, type DuplicateSongGroup } from "../api";
import { clock } from "../audio";
import { t as tr } from "../i18n";

function line(s: DuplicateSong) {
  return [s.codec?.toUpperCase(), formatBytes(s.size), s.duration ? clock(s.duration) : null].filter(Boolean).join(" · ");
}

export default function DuplicateSongs() {
  const [groups, setGroups] = useState<DuplicateSongGroup[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const load = () => api.songDuplicates().then(setGroups).catch((e) => setMsg((e as Error).message));
  useEffect(() => { void load(); }, []);
  const check = async () => {
    setBusy(true); setMsg("");
    try {
      const r = await api.checkSongDuplicates();
      setMsg(r.hidden ? tr("Took {n} more duplicate songs out of Listen.", { n: r.hidden }) : tr("No new duplicates."));
      await load();
    } catch (e) { setMsg((e as Error).message); } finally { setBusy(false); }
  };
  const keep = async (id: string) => {
    try { await api.keepSongCopy(id); await load(); } catch (e) { setMsg((e as Error).message); }
  };
  const count = groups?.reduce((n, g) => n + g.copies.length, 0) ?? 0;
  return (
    <section className="panel dup-songs">
      <h2><CopyX size={18} aria-hidden />{" "}{tr("Duplicate songs")}</h2>
      <p className="muted small">
        {tr("After every music scan (and each night) ZiraHive looks for songs that are there more than once, keeps the best copy and takes the others out of Listen. Plays, favourites and playlists move to the copy that stays. Copies are moved into a .zirahive-duplicates folder inside the category when ZiraHive may write there; otherwise they're only hidden. Nothing is deleted.")}
      </p>
      <div className="admin-row">
        <button onClick={() => void check()} disabled={busy}>{busy ? tr("Checking…") : tr("Check now")}</button>
        {groups && <span className="muted small">{count === 1 ? tr("1 copy taken out") : count ? tr("{n} copies taken out", { n: count }) : tr("No duplicates found.")}</span>}
      </div>
      {msg && <p role="status">{msg}</p>}
      {groups && groups.length > 0 && (
        <ul className="dup-song-list">
          {groups.map((g) => (
            <li key={g.keep.id}>
              <div className="dup-keep">
                <strong>{g.keep.title}</strong>{g.keep.artist && <span className="muted"> · {g.keep.artist}</span>}
                <div className="muted small">{tr("Kept")}: {g.keep.library} / {g.keep.path} <span className="nowrap">({line(g.keep)})</span></div>
              </div>
              <ul>
                {g.copies.map((c) => (
                  <li key={c.id}>
                    <span className="small">
                      {c.library} / {c.path} <span className="muted nowrap">({line(c)})</span>
                      {" "}<span className="tag">{c.moved ? tr("moved aside") : tr("hidden")}</span>
                    </span>
                    <button className="link-btn small" onClick={() => void keep(c.id)}>{tr("Keep both")}</button>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
