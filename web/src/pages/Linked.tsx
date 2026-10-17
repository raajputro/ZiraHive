// Watching what a linked GharBox shares: its categories, series and a player. Everything is
// fetched through this server (/api/links/...), which also keeps where you stopped.
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Check, ChevronRight, Link2, Play, SkipForward } from "lucide-react";
import { api, url, episodeCode, formatDuration, type LinkedServer, type Media, type Quality, type SeriesDetail, type Title, type Tracks } from "../api";
import { usePrefs } from "../prefs";
import { defaultAudio, defaultQuality, SubtitleTracks, TrackMenus, useSubtitle, useVideoSource } from "../video";
import { TitleCard } from "./Watch";
import { t as tr } from "../i18n";

const VIDEO = new Set(["movies", "shows", "mixed"]);

/** "From Rahim's GharBox" rows on the Watch home page. */
export function LinkedShelves() {
  const [links, setLinks] = useState<LinkedServer[]>([]);
  const [shelves, setShelves] = useState<Record<string, Title[]>>({});
  useEffect(() => { api.links().then(setLinks).catch(() => undefined); }, []);
  useEffect(() => {
    for (const l of links) for (const lib of l.libraries.filter((x) => VIDEO.has(x.kind)))
      api.linkTitles(l.id, lib.id).then((t) => setShelves((s) => ({ ...s, [`${l.id}/${lib.id}`]: t.slice(0, 24) }))).catch(() => undefined);
  }, [links]);
  return (
    <>
      {links.map((l) => l.ok ? l.libraries.filter((x) => VIDEO.has(x.kind)).map((lib) => (
        <section key={`${l.id}/${lib.id}`} className="shelf-block">
          <Link to={`/watch/link/${l.id}/${lib.id}`} className="shelf-title link">
            <Link2 size={16} aria-hidden />{" "}{lib.name}{" "}<span className="muted small">{tr("from {name}", { name: l.name })}</span>
            <ChevronRight size={18} aria-hidden />
          </Link>
          <div className="shelf">{(shelves[`${l.id}/${lib.id}`] ?? []).map((t) => <TitleCard key={t.id} t={t} link={l.id} />)}</div>
        </section>
      )) : (
        <p key={l.id} className="muted small"><Link2 size={14} aria-hidden />{" "}{tr("{name} can't be reached right now.", { name: l.name })}</p>
      ))}
    </>
  );
}

export function LinkLibraryPage() {
  const { linkId = "", libraryId = "" } = useParams();
  const [link, setLink] = useState<LinkedServer | null>(null);
  const [titles, setTitles] = useState<Title[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api.links().then((all) => setLink(all.find((l) => l.id === linkId) ?? null)).catch(() => undefined);
    api.linkTitles(linkId, libraryId).then(setTitles).catch((e) => setError(e.message));
  }, [linkId, libraryId]);
  const lib = link?.libraries.find((l) => l.id === libraryId);
  return (
    <div className="page cinema-page">
      <Link to="/watch" className="back"><ArrowLeft size={18} />{" "}{tr("Watch")}</Link>
      <header className="page-head">
        <h1>{lib?.name ?? "…"}</h1>
        {link && <p className="muted"><Link2 size={15} aria-hidden />{" "}{tr("from {name}", { name: link.name })}</p>}
      </header>
      {error && <p className="error">{error}</p>}
      {titles && titles.length === 0 && <p className="muted">{tr("Nothing here yet.")}</p>}
      {titles && <div className="poster-grid">{titles.map((t) => <TitleCard key={t.id} t={t} link={linkId} />)}</div>}
    </div>
  );
}

export function LinkSeriesPage() {
  const { linkId = "", seriesId = "" } = useParams();
  const [s, setS] = useState<SeriesDetail | null>(null);
  const [season, setSeason] = useState<number | null | undefined>(undefined);
  const [error, setError] = useState("");
  useEffect(() => {
    api.linkSeries(linkId, seriesId).then((d) => { setS(d); setSeason(d.up_next?.season ?? d.seasons[0]?.season ?? null); })
      .catch((e) => setError(e.message));
  }, [linkId, seriesId]);
  if (error) return <div className="page cinema-page"><p className="error">{error}</p></div>;
  if (!s) return <div className="page cinema-page" aria-busy="true" />;
  const current = s.seasons.find((x) => x.season === season) ?? s.seasons[0];
  const next = s.up_next;
  return (
    <div className="page cinema-page">
      <Link to={`/watch/link/${linkId}/${s.library_id}`} className="back"><ArrowLeft size={18} />{" "}{tr("Back")}</Link>
      <header className="series-head">
        <div className="series-poster">
          {s.poster_ready ? <img src={url.linkPoster(linkId, { id: s.id, type: "series" })} alt="" /> : <span className="poster-blank">{s.title}</span>}
        </div>
        <div className="series-info">
          <h1>{s.title}</h1>
          <p className="muted">{[s.year, tr("{n} episodes", { n: s.episode_count })].filter(Boolean).join(", ")}</p>
          {s.overview && <p className="overview">{s.overview}</p>}
          {next && (
            <Link to={`/play/link/${linkId}/${next.id}`} className="button primary play-btn">
              <Play size={18} fill="currentColor" />{" "}{next.position > 30 ? tr("Resume {code}", { code: episodeCode(next) }) : tr("Play {code}", { code: episodeCode(next) })}
            </Link>
          )}
        </div>
      </header>
      {s.seasons.length > 1 && (
        <div className="lib-tabs season-tabs" role="tablist" aria-label={tr("Seasons")}>
          {s.seasons.map((x) => (
            <button key={String(x.season)} role="tab" aria-selected={x.season === current.season}
              className={x.season === current.season ? "active" : ""} onClick={() => setSeason(x.season)}>
              {x.season != null ? tr("Season {season}", { season: x.season }) : tr("Other")}
            </button>
          ))}
        </div>
      )}
      <ol className="episodes">
        {current.episodes.map((e) => {
          const pct = e.duration && e.position ? Math.min(100, (e.position / e.duration) * 100) : 0;
          return (
            <li key={e.id}>
              <Link to={`/play/link/${linkId}/${e.id}`} className="episode">
                <div className="episode-still">
                  {e.poster_ready ? <img src={url.poster(e)} alt="" loading="lazy" /> : <span />}
                  {pct > 0 && !e.finished && <span className="poster-progress"><span style={{ width: `${pct}%` }} /></span>}
                </div>
                <div className="episode-text">
                  <span className="episode-code">{episodeCode(e)}</span>
                  <span className="episode-title">{e.episode_title ?? e.title}</span>
                  <span className="muted small">{formatDuration(e.duration)}</span>
                </div>
                {e.finished && <Check size={18} className="watched" aria-label={tr("Watched")} />}
              </Link>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

export function LinkPlayerPage() {
  const { linkId = "", mediaId = "" } = useParams();
  const navigate = useNavigate();
  const { lowData } = usePrefs();
  const video = useRef<HTMLVideoElement>(null);
  const [m, setM] = useState<Media | null>(null);
  const [tracks, setTracks] = useState<Tracks | null>(null);
  const [quality, setQuality] = useState<Quality | null>(null);
  const [audio, setAudio] = useState(0);
  const [subtitle, setSubtitle] = useState("off");
  const [error, setError] = useState("");
  const resumeAt = useRef<number | null>(null);
  const lastSaved = useRef(0);

  useEffect(() => {
    Promise.all([api.linkMedia(linkId, mediaId), api.linkTracks(linkId, mediaId)]).then(([media, t]) => {
      setM(media); setTracks(t); setAudio(defaultAudio(t)); setQuality(defaultQuality(t, lowData));
      const forced = t.subtitles.find((x) => x.forced && x.usable);
      if (forced) setSubtitle(forced.id);
      resumeAt.current = media.position > 5 && !media.finished ? media.position : null;
    }).catch((e) => setError(e.message));
  }, [linkId, mediaId, lowData]);
  useVideoSource(video, { media: m, tracks, quality, audio, startAt: resumeAt, autoplay: true, onError: setError });
  useSubtitle(video, subtitle, [m, quality, audio]);

  const save = () => {
    const v = video.current;
    if (!v || !m || !v.currentTime) return Promise.resolve();
    lastSaved.current = Date.now();
    const title = m.series_title ? `${m.series_title} ${episodeCode(m)}` : m.title;
    return api.linkProgress(linkId, m.id, v.currentTime, v.duration || m.duration || undefined, title).catch(() => undefined);
  };
  useEffect(() => () => { void save(); }, [m]);  // eslint-disable-line react-hooks/exhaustive-deps

  if (error && !m) return <div className="page cinema-page"><p className="error">{error}</p></div>;
  if (!m || !tracks || !quality) return <div className="page cinema-page" aria-busy="true" />;
  const back = m.series_id ? `/watch/link/${linkId}/series/${m.series_id}` : `/watch/link/${linkId}/${m.library_id}`;
  const playNext = async () => { await save(); navigate(`/play/link/${linkId}/${m.next_id}`, { replace: true }); };
  return (
    <div className="player-page">
      <Link to={back} className="back"><ArrowLeft size={18} />{" "}{m.series_title ?? tr("Back")}</Link>
      <div className="player-frame">
        <video ref={video} controls playsInline poster={m.poster_ready ? url.poster(m) : undefined}
          onTimeUpdate={() => { if (Date.now() - lastSaved.current > 10_000) void save(); }}
          onPause={() => void save()} onEnded={() => { if (m.next_id) void playNext(); else void save(); }}>
          <SubtitleTracks media={m} tracks={tracks} />
        </video>
      </div>
      <div className="player-controls">
        <TrackMenus tracks={tracks} quality={quality} setQuality={setQuality} audio={audio} setAudio={setAudio}
          subtitle={subtitle} setSubtitle={setSubtitle} />
        {m.next_id && <button onClick={() => void playNext()}><SkipForward size={16} />{" "}{tr("Next episode")}</button>}
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="player-info">
        {m.series_title ? <><p className="episode-code">{m.series_title}, {episodeCode(m)}</p><h1>{m.episode_title ?? m.title}</h1></> : <h1>{m.title}</h1>}
        <p className="muted">{[m.year, formatDuration(m.duration), m.height ? `${m.height}p` : null].filter(Boolean).join(", ")}</p>
        {m.overview && <p className="overview">{m.overview}</p>}
        <p className="muted small"><Link2 size={14} aria-hidden />{" "}{tr("From a linked GharBox. Where you stop is saved here.")}</p>
      </div>
    </div>
  );
}
