import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import Hls from "hls.js";
import { ArrowLeft, SkipForward, Download, ExternalLink, FastForward } from "lucide-react";
import { api, url, episodeCode, formatBytes, formatDuration, AGE_LABEL, AGE_OPTIONS,
  type Media, type OfflineCopy, type Quality, type Tracks } from "../api";
import { useAuth } from "../App";
import { usePrefs } from "../prefs";

// Remount for every title so progress is always saved against the right one.
export default function PlayerRoute() {
  const { id } = useParams();
  return id ? <Player key={id} id={id} /> : null;
}

const QUALITY_LABEL: Record<Quality, string> = {
  original: "Original", "1080p": "1080p", "720p": "720p", "480p": "480p (saves data)", "360p": "360p (lowest data)",
};
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
  const video = useRef<HTMLVideoElement>(null);
  const hls = useRef<Hls | null>(null);
  const lastSaved = useRef(0);
  const resumeAt = useRef<number | null>(null);
  const dismissedNext = useRef(false);

  useEffect(() => {
    Promise.all([api.mediaItem(id), api.tracks(id)]).then(([media, t]) => {
      setM(media);
      setTracks(t);
      setAudio(t.audio.find((a) => a.default)?.index ?? 0);
      const forced = t.subtitles.find((s) => s.forced && s.usable);
      if (forced) setSubtitle(forced.id);
      // Low-data mode starts at 480p; otherwise play the file as it is when the browser can.
      const small = t.qualities.find((q) => q === "480p") ?? t.qualities[t.qualities.length - 1];
      setQuality(lowData ? small : t.direct_play ? "original" : t.qualities[0]);
      resumeAt.current = media.position > 5 && !media.finished ? media.position : null;
    }).catch((e) => setError(e.message));
  }, [id, lowData]);

  // (Re)load the video whenever quality or audio track changes, keeping the position.
  useEffect(() => {
    const v = video.current;
    if (!v || !m || !tracks || !quality) return;
    const at = resumeAt.current ?? (v.currentTime > 0 ? v.currentTime : 0);
    resumeAt.current = null;
    hls.current?.destroy();
    hls.current = null;
    const defaultAudio = tracks.audio.find((a) => a.default)?.index ?? 0;
    const direct = quality === "original" && tracks.direct_play && audio === defaultAudio;
    const resume = () => { if (at > 0) v.currentTime = at; };
    if (direct) {
      v.src = url.stream(m);
      v.addEventListener("loadedmetadata", resume, { once: true });
    } else {
      const q = quality === "original" ? tracks.qualities[0] : quality;
      const src = url.hls(m, q, audio);
      if (Hls.isSupported()) {
        const h = new Hls({ startPosition: at, maxBufferLength: 30, xhrSetup: (xhr) => { xhr.withCredentials = true; } });
        h.loadSource(src);
        h.attachMedia(v);
        h.on(Hls.Events.ERROR, (_e, data) => {
          console.warn("video stream:", data.type, data.details, data.fatal ? "(fatal)" : "", data.error?.message ?? "");
          if (!data.fatal) return;
          if (data.response?.code === 503) setError("The server is busy converting other videos. Try again in a minute, or choose Original.");
          else if (String(data.details).toLowerCase().includes("codec")) setError("This browser can't play H.264 video. Use Chrome, Edge, Firefox or Safari.");
          else setError("This video couldn't be converted. Try another quality.");
        });
        hls.current = h;
      } else {
        v.src = src;  // Safari plays HLS itself
        v.addEventListener("loadedmetadata", resume, { once: true });
      }
    }
    void v.play().catch(() => undefined);
    return () => { hls.current?.destroy(); hls.current = null; };
  }, [m, tracks, quality, audio]);

  // Show the chosen subtitles
  useEffect(() => {
    const v = video.current;
    if (!v) return;
    for (const t of Array.from(v.textTracks)) t.mode = t.id === subtitle ? "showing" : "disabled";
  }, [subtitle, m, quality, audio]);

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
  const qualities: Quality[] = [...(tracks.direct_play ? ["original" as Quality] : []), ...tracks.qualities];

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
          {tracks.subtitles.filter((s) => s.usable).map((s) => (
            <track key={s.id} id={s.id} kind="subtitles" label={s.label} srcLang={s.language ?? undefined} src={url.subtitle(m, s.id)} />
          ))}
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
        <label>Quality
          <select value={quality} onChange={(e) => setQuality(e.target.value as Quality)}>
            {qualities.map((q) => <option key={q} value={q}>{QUALITY_LABEL[q]}</option>)}
          </select>
        </label>
        {tracks.audio.length > 1 && (
          <label>Audio
            <select value={audio} onChange={(e) => setAudio(Number(e.target.value))}>
              {tracks.audio.map((a) => <option key={a.index} value={a.index}>{a.label}</option>)}
            </select>
          </label>
        )}
        {tracks.subtitles.some((s) => s.usable) && (
          <label>Subtitles
            <select value={subtitle} onChange={(e) => setSubtitle(e.target.value)}>
              <option value="off">Off</option>
              {tracks.subtitles.filter((s) => s.usable).map((s) => <option key={s.id} value={s.id}>{s.label}{s.forced ? " (forced)" : ""}</option>)}
            </select>
          </label>
        )}
        {m.next_id && <button onClick={() => void playNext()}><SkipForward size={16} /> Next episode</button>}
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
