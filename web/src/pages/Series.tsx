import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Play, Check, Timer, PartyPopper } from "lucide-react";
import PartyDialog from "../components/PartyDialog";
import { api, ApiError, url, clock, parseClock, episodeCode, formatDuration, AGE_LABEL, type SeriesDetail } from "../api";
import { useAuth } from "../App";
import Dialog from "../components/Dialog";
import { RatingControl } from "./Player";

export default function SeriesPage() {
  const { id } = useParams();
  const [s, setS] = useState<SeriesDetail | null>(null);
  const [season, setSeason] = useState<number | null | undefined>(undefined);
  const [error, setError] = useState("");
  const [markers, setMarkers] = useState(false);
  const [together, setTogether] = useState(false);
  const { user } = useAuth();

  useEffect(() => {
    if (!id) return;
    api.series(id).then((data) => {
      setS(data);
      setSeason(data.up_next?.season ?? data.seasons[0]?.season ?? null);
    }).catch((e) => setError(e.message));
  }, [id]);

  if (error) return <div className="page cinema-page"><p className="error">{error}</p></div>;
  if (!s) return <div className="page cinema-page" aria-busy="true" />;

  const current = s.seasons.find((x) => x.season === season) ?? s.seasons[0];
  const next = s.up_next;
  const label = !next ? null
    : next.position > 30 ? `Resume ${episodeCode(next)}` : `Play ${episodeCode(next)}`;

  return (
    <div className="page cinema-page">
      <Link to={`/watch/c/${s.library_id}`} className="back"><ArrowLeft size={18} /> Back</Link>
      <header className="series-head">
        <div className="series-poster">
          {s.poster_ready ? <img src={url.seriesPoster(s)} alt="" /> : <span className="poster-blank">{s.title}</span>}
        </div>
        <div className="series-info">
          <h1>{s.title}</h1>
          <p className="muted">
            {[s.year, `${s.seasons.length} season${s.seasons.length === 1 ? "" : "s"}`, `${s.episode_count} episodes`,
              s.age != null ? AGE_LABEL[s.age] : null].filter(Boolean).join(", ")}
          </p>
          {s.overview && <p className="overview">{s.overview}</p>}
          {next && label && (
            <div className="admin-row">
              <Link to={`/play/${next.id}`} className="button primary play-btn"><Play size={18} fill="currentColor" /> {label}</Link>
              <button className="play-btn" onClick={() => setTogether(true)}><PartyPopper size={17} /> Watch together</button>
            </div>
          )}
          {together && next && <PartyDialog mediaId={next.id} title={`${s.title} ${episodeCode(next)}`} onClose={() => setTogether(false)} />}
          {!next && <p className="muted">You've watched every episode.</p>}
          {user.is_admin && (
            <div className="admin-row">
              <RatingControl value={s.age_rating} onChange={(v) => api.setSeriesRating(s.id, v)} label="Suitable for" />
              <button onClick={() => setMarkers(true)}><Timer size={16} /> Intro and credits</button>
            </div>
          )}
        </div>
      </header>

      {s.seasons.length > 1 && (
        <div className="lib-tabs season-tabs" role="tablist" aria-label="Seasons">
          {s.seasons.map((x) => (
            <button key={String(x.season)} role="tab" aria-selected={x.season === current.season}
              className={x.season === current.season ? "active" : ""} onClick={() => setSeason(x.season)}>
              {x.season != null ? `Season ${x.season}` : "Other"}
            </button>
          ))}
        </div>
      )}

      {markers && <MarkersDialog series={s} onClose={() => setMarkers(false)} onSaved={(n) => { setS(n); setMarkers(false); }} />}
      <ol className="episodes">
        {current.episodes.map((e) => {
          const pct = e.duration && e.position ? Math.min(100, (e.position / e.duration) * 100) : 0;
          return (
            <li key={e.id}>
              <Link to={`/play/${e.id}`} className="episode">
                <div className="episode-still">
                  {e.poster_ready ? <img src={url.poster(e)} alt="" loading="lazy" /> : <span />}
                  {pct > 0 && !e.finished && <span className="poster-progress"><span style={{ width: `${pct}%` }} /></span>}
                </div>
                <div className="episode-text">
                  <span className="episode-code">{episodeCode(e)}</span>
                  <span className="episode-title">{e.episode_title ?? e.title}</span>
                  <span className="muted small">{formatDuration(e.duration)}</span>
                </div>
                {e.finished && <Check size={18} className="watched" aria-label="Watched" />}
              </Link>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function MarkersDialog({ series, onClose, onSaved }: { series: SeriesDetail; onClose: () => void; onSaved: (s: SeriesDetail) => void }) {
  const fmt = (v: number | null) => (v == null ? "" : clock(v));
  const [start, setStart] = useState(fmt(series.intro_start));
  const [end, setEnd] = useState(fmt(series.intro_end));
  const [credits, setCredits] = useState(fmt(series.credits_before_end));
  const [error, setError] = useState("");
  const save = async (e: FormEvent) => {
    e.preventDefault();
    const [a, b, c] = [parseClock(start), parseClock(end), parseClock(credits)];
    if (a === undefined || b === undefined || c === undefined) { setError("Write times like 1:30 or 0:45."); return; }
    if ((a != null || b != null) && b == null) { setError("Add where the intro ends."); return; }
    try { onSaved(await api.setSeriesMarkers(series.id, { intro_start: b != null ? a ?? 0 : null, intro_end: b, credits_before_end: c })); }
    catch (err) { setError(err instanceof ApiError ? err.message : "Couldn't save"); }
  };
  return (
    <Dialog title={`Intro and credits for ${series.title}`} onClose={onClose}>
      <p className="muted small">These apply to every episode. Episodes whose files have chapters named Intro or Credits use those instead.
        Leave a field empty to turn it off.</p>
      <form className="stack-form" onSubmit={save}>
        <div className="inline-form">
          <label>Intro starts at<input value={start} onChange={(e) => setStart(e.target.value)} placeholder="0:30" inputMode="numeric" /></label>
          <label>Intro ends at<input value={end} onChange={(e) => setEnd(e.target.value)} placeholder="1:45" inputMode="numeric" /></label>
        </div>
        <label>End credits last<input value={credits} onChange={(e) => setCredits(e.target.value)} placeholder="1:10" inputMode="numeric" /></label>
        <p className="muted small">When the credits start, the next episode counts down and plays by itself.</p>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="primary">Save</button>
      </form>
    </Dialog>
  );
}
