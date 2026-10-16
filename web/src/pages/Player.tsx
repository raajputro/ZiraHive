import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, SkipForward, Download, ExternalLink, FastForward, PartyPopper } from "lucide-react";
import PartyDialog from "../components/PartyDialog";
import { api, url, episodeCode, formatBytes, formatDuration, AGE_LABEL, AGE_OPTIONS,
  type Media, type OfflineCopy, type Quality, type Tracks } from "../api";
import { useAuth } from "../App";
import { usePrefs } from "../prefs";
import { defaultAudio, defaultQuality, SubtitleTracks, TrackMenus, useSubtitle, useVideoSource } from "../video";

// Remount for every title so progress is always saved against the right one.
export default function PlayerRoute() {
  const { id } = useParams();
  return id ? <Player key={id} id={id} /> : null;
}

const COUNTDOWN = 10;

function Player({ id }: { id: string }) {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { lowData } = usePrefs();
  const [m, setM] = useState<Media | null>(null);
  const [tracks, setTracks] = useState<Tracks | null>(null);
  const [error, setError] = useState("");
  const [quality, setQuality] = useState<Quality | null>(null);
  const [audio, setAudio] = useState(0);
  const [subtitle, setSubtitle] = useState("off");
  const [time, setTime] = useState(0);
  const [countdown, setCountdown] = useState<number | null>(null);
  const [link, setLink] = useState("");
  const [together, setTogether] = useState(false);
  const video = useRef<HTMLVideoElement>(null);
  const lastSaved = useRef(0);
  const resumeAt = useRef<number | null>(null);
  const dismissedNext = useRef(false);

  useEffect(() => {
    Promise.all([api.mediaItem(id), api.tracks(id)]).then(([media, t]) => {
      setM(media);
      setTracks(t);
      setAudio(defaultAudio(t));
      const forced = t.subtitles.find((s) => s.forced && s.usable);
      if (forced) setSubtitle(forced.id);
      setQuality(defaultQuality(t, lowData));
      resumeAt.current = media.position > 5 && !media.finished ? media.position : null;
    }).catch((e) => setError(e.message));
  }, [id, lowData]);

  useVideoSource(video, { media: m, tracks, quality, audio, startAt: resumeAt, autoplay: true, onError: setError });
  useSubtitle(video, subtitle, [m, quality, audio]);

  useEffect(() => { api.streamLink(id).then((r) => setLink(location.origin + r.path)).catch(() => undefined); }, [id]);

  const save = () => {
    const v = video.current;
    if (!v || !m || !v.currentTime) return Promise.resolve();
    lastSaved.current = Date.now();
    return api.saveProgress(m.id, v.currentTime, v.duration || m.duration || undefined).catch(() => undefined);
  };
  useEffect(() => {
    const onHide = () => void save();
    window.addEventListener("pagehide", onHide);
    return () => { window.removeEventListener("pagehide", onHide); void save(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [m]);

  const playNext = async () => {
    if (!m?.next_id) return;
    await save();
    navigate(`/play/${m.next_id}`, { replace: true });
  };

  // Next-episode countdown once the credits start
  const creditsAt = m?.credits_start ?? (m?.duration ? m.duration - 25 : null);
  const inCredits = !!(m?.next_id && creditsAt && time >= creditsAt);
  useEffect(() => {
    if (!inCredits || dismissedNext.current) { setCountdown(null); return; }
    setCountdown((c) => c ?? COUNTDOWN);
  }, [inCredits]);
  useEffect(() => {
    if (countdown === null) return;
    if (countdown <= 0) { void playNext(); return; }
    const t = setTimeout(() => setCountdown((c) => (c === null ? null : c - 1)), 1000);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [countdown]);

  if (error && !m) return <div className="page cinema-page"><p className="error">{error}</p></div>;
  if (!m || !tracks || !quality) return <div className="page cinema-page" aria-busy="true" />;

  const isEpisode = !!m.series_id;
  const inIntro = m.intro_end != null && time >= (m.intro_start ?? 0) && time < m.intro_end - 1;
  const details = [!isEpisode && m.year, formatDuration(m.duration), m.height ? `${m.height}p` : null,
    m.age != null ? AGE_LABEL[m.age] : null, formatBytes(m.size)].filter(Boolean);

  return (
    <div className="player-page">
      {isEpisode
        ? <Link to={`/watch/series/${m.series_id}`} className="back"><ArrowLeft size={18} /> {m.series_title}</Link>
        : <Link to={`/watch/c/${m.library_id}`} className="back"><ArrowLeft size={18} /> Back</Link>}
      <div className="player-frame">
        <video ref={video} controls playsInline poster={m.poster_ready ? url.poster(m) : undefined}
          preload={lowData ? "none" : "metadata"}
          onTimeUpdate={(e) => {
            setTime(e.currentTarget.currentTime);
            if (Date.now() - lastSaved.current > 10_000) void save();
          }}
          onSeeked={() => { dismissedNext.current = false; }}
          onPause={() => void save()}
          onEnded={() => { if (m.next_id) void playNext(); else void save(); }}>
          <SubtitleTracks media={m} tracks={tracks} />
        </video>
        {inIntro && (
          <button className="overlay-btn skip" onClick={() => { if (video.current) video.current.currentTime = m.intro_end!; }}>
            <FastForward size={17} /> Skip intro
          </button>
        )}
        {countdown !== null && (
          <div className="overlay-next" role="status">
            <span>Next episode in {countdown}</span>
            <button className="primary" onClick={() => void playNext()}><SkipForward size={16} /> Play now</button>
            <button onClick={() => { dismissedNext.current = true; setCountdown(null); }}>Keep watching</button>
          </div>
        )}
      </div>

      <div className="player-controls">
        <TrackMenus tracks={tracks} quality={quality} setQuality={setQuality} audio={audio} setAudio={setAudio}
          subtitle={subtitle} setSubtitle={setSubtitle} />
        {m.next_id && <button onClick={() => void playNext()}><SkipForward size={16} /> Next episode</button>}
        <button onClick={() => { video.current?.pause(); setTogether(true); }}><PartyPopper size={16} /> Watch together</button>
      </div>
      {error && <p className="error" role="alert">{error}</p>}

      <div className="player-info">
        {isEpisode ? (
          <>
            <p className="episode-code">{m.series_title}, {episodeCode(m)}</p>
            <h1>{m.episode_title ?? m.title}</h1>
          </>
        ) : <h1>{m.title}</h1>}
        <p className="muted">{details.join(", ")}</p>
        {m.overview && <p className="overview">{m.overview}</p>}
        {together && <PartyDialog mediaId={m.id} title={isEpisode ? `${m.series_title} ${episodeCode(m)}` : m.title} onClose={() => setTogether(false)} />}
        <OfflinePanel media={m} qualities={tracks.qualities} />
        {user.is_admin && !isEpisode && <RatingControl value={m.age} onChange={(v) => api.setMediaRating(m.id, v)} label="Suitable for" />}
        <details className="more">
          <summary><ExternalLink size={15} /> Open in another player</summary>
          <p className="muted small">For VLC on a TV or phone: Media, Open Network Stream, then paste this address. It works for 24 hours.</p>
          <code>{link || "loading…"}</code>
          <button onClick={() => void navigator.clipboard?.writeText(link)} disabled={!link}>Copy address</button>
        </details>
      </div>
    </div>
  );
}

function OfflinePanel({ media, qualities }: { media: Media; qualities: string[] }) {
  const [copies, setCopies] = useState<OfflineCopy[]>([]);
  const [quality, setQuality] = useState(qualities.includes("480p") ? "480p" : qualities[qualities.length - 1]);
  const [msg, setMsg] = useState("");
  const load = () => api.offlineCopies(media.id).then(setCopies).catch(() => undefined);
  useEffect(() => { void load(); /* eslint-disable-next-line */ }, [media.id]);
  const working = copies.some((c) => c.status === "queued" || c.status === "working");
  useEffect(() => {
    if (!working) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [working]);
  const make = async () => {
    setMsg("");
    try { await api.requestOffline(media.id, quality); await load(); }
    catch (e) { setMsg(e instanceof Error ? e.message : "Couldn't start"); }
  };
  return (
    <section className="offline">
      <h2><Download size={17} aria-hidden /> Watch without internet</h2>
      <p className="muted small">GharBox makes a smaller copy you can save on your phone or laptop. You'll get a notification when it's ready.</p>
      {copies.map((c) => (
        <div key={c.id} className="offline-row">
          <strong>{c.quality}</strong>
          {c.status === "ready" && <><span className="muted small">{formatBytes(c.size ?? 0)}</span>
            <a className="button primary" href={url.offlineFile(c)}><Download size={15} /> Save file</a></>}
          {(c.status === "queued" || c.status === "working") && (
            <><div className="disk" role="progressbar" aria-valuenow={Math.round(c.progress * 100)} aria-valuemin={0} aria-valuemax={100}>
              <span style={{ width: `${c.progress * 100}%` }} /></div>
              <span className="muted small">{c.status === "queued" ? "waiting" : `${Math.round(c.progress * 100)}%`}</span></>
          )}
          {c.status === "failed" && <span className="error small">Failed: {c.error}</span>}
        </div>
      ))}
      <div className="inline-form">
        <label>Quality
          <select value={quality} onChange={(e) => setQuality(e.target.value)}>
            {qualities.map((q) => <option key={q} value={q}>{q}</option>)}
          </select>
        </label>
        <button onClick={() => void make()}>Make a copy</button>
      </div>
      {msg && <p className="error">{msg}</p>}
    </section>
  );
}

export function RatingControl({ value, onChange, label }: { value: number | null; onChange: (v: number | null) => Promise<void>; label: string }) {
  const [v, setV] = useState<number | null>(value);
  const [saved, setSaved] = useState(false);
  return (
    <label className="rating-control">{label}
      <select value={v ?? ""} onChange={async (e) => {
        const next = e.target.value === "" ? null : Number(e.target.value);
        setV(next); await onChange(next); setSaved(true); setTimeout(() => setSaved(false), 1500);
      }}>
        <option value="">Not rated</option>
        {AGE_OPTIONS.map((a) => <option key={a} value={a}>{AGE_LABEL[a]}</option>)}
      </select>
      {saved && <span className="muted small"> Saved</span>}
    </label>
  );
}
