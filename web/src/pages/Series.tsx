import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Play, Check } from "lucide-react";
import { api, url, episodeCode, formatDuration, type SeriesDetail } from "../api";

export default function SeriesPage() {
  const { id } = useParams();
  const [s, setS] = useState<SeriesDetail | null>(null);
  const [season, setSeason] = useState<number | null | undefined>(undefined);
  const [error, setError] = useState("");

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
            {[s.year, `${s.seasons.length} season${s.seasons.length === 1 ? "" : "s"}`, `${s.episode_count} episodes`].filter(Boolean).join(", ")}
          </p>
          {s.overview && <p className="overview">{s.overview}</p>}
          {next && label && (
            <Link to={`/play/${next.id}`} className="button primary play-btn"><Play size={18} fill="currentColor" /> {label}</Link>
          )}
          {!next && <p className="muted">You've watched every episode.</p>}
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
