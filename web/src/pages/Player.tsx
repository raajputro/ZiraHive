import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Cast, Pause, Play, Sparkles, Square, SkipForward, Download, ExternalLink, FastForward, PartyPopper } from "lucide-react";
import { castProblem, castTo, loadCast, type CastControl, type CastState } from "../cast";
import PartyDialog from "../components/PartyDialog";
import { api, ApiError, url, episodeCode, formatBytes, formatDuration, AGE_LABEL, AGE_OPTIONS,
  type Media, type OfflineCopy, type Quality, type Tracks } from "../api";
import { useAuth } from "../App";
import { usePrefs } from "../prefs";
import { defaultAudio, defaultQuality, SubtitleTracks, TrackMenus, useSubtitle, useVideoSource } from "../video";

import { digits, t as tr } from "../i18n";

const clock = (sec: number) => {
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = Math.floor(sec % 60);
  return digits(`${h ? `${h}:${String(m).padStart(2, "0")}` : m}:${String(s).padStart(2, "0")}`);
};
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
  const [cast, setCast] = useState<CastControl | null>(null);
  const [castState, setCastState] = useState<CastState | null>(null);
  const [castHelp, setCastHelp] = useState("");
  const [castBusy, setCastBusy] = useState(false);
  const castTime = useRef(0);
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

  // Chromecast: the TV plays it by itself; this page becomes the remote
  const startCast = async () => {
    if (!m || !quality) return;
    setCastHelp("");
    const problem = castProblem();
    if (problem === "insecure") {
      setCastHelp(tr("Casting needs a secure page. Open ZiraHive with https (your online address), or as http://localhost:8080 on the server PC, then try again. On an iPhone or Mac, use AirPlay in the video's own controls."));
      return;
    }
    if (problem === "browser") {
      setCastHelp(tr("Casting works in Chrome and Edge. In this browser, use \"Open in another player\" below, or AirPlay on an iPhone or Mac."));
      return;
    }
    setCastBusy(true);
    try {
      if (!(await loadCast())) {
        setCastHelp(tr("Google's Cast library couldn't be loaded. Check the internet connection and try again."));
        return;
      }
      const info = await api.castInfo(m.id, quality, audio);
      const v = video.current;
      if (v && v.currentTime > 5) info.start = v.currentTime;
      v?.pause();
      const ctl = await castTo(info, subtitle);
      setCast(ctl);
    } catch (e) {
      if (e instanceof Error && e.message !== "cancelled" && !/cancel/i.test(e.message)) {
        setCastHelp(e instanceof ApiError ? e.message : tr("Couldn't start playing on the TV. Check that it's on the same Wi-Fi as ZiraHive."));
      }
    } finally { setCastBusy(false); }
  };
  useEffect(() => {
    if (!cast || !m) return;
    let saved = 0;
    const stop = cast.watch((st) => {
      setCastState(st);
      if (!st) {  // stopped from here, the TV or the phone's notification
        setCast(null);
        const v = video.current;
        if (v && castTime.current > 0) v.currentTime = castTime.current;
        return;
      }
      castTime.current = st.time;
      if (st.time > 0 && Date.now() - saved > 10_000) {
        saved = Date.now();
        void api.saveProgress(m.id, st.time, st.duration || m.duration || undefined).catch(() => undefined);
      }
    });
    return () => {
      stop();
      if (castTime.current > 0) void api.saveProgress(m.id, castTime.current, m.duration || undefined).catch(() => undefined);
    };
  }, [cast, m]);

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
        : <Link to={`/watch/c/${m.library_id}`} className="back"><ArrowLeft size={18} />{" "}{tr("Back")}</Link>}
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
        {cast && (
          <div className="cast-panel" role="group" aria-label={tr("Playing on the TV")}>
            <p><Cast size={20} aria-hidden />{" "}{tr("Playing on {device}", { device: castState?.device ?? "Chromecast" })}</p>
            <input type="range" min={0} max={Math.max(1, Math.round(castState?.duration ?? m.duration ?? 0))}
              value={Math.round(castState?.time ?? 0)} aria-label={tr("Position")}
              onChange={(e) => cast.seek(Number(e.target.value))} />
            <p className="muted small">{clock(castState?.time ?? 0)} / {clock(castState?.duration ?? m.duration ?? 0)}</p>
            <div className="admin-row">
              <button className="primary" onClick={() => cast.playPause()}>
                {castState?.playing ? <><Pause size={16} />{" "}{tr("Pause")}</> : <><Play size={16} />{" "}{tr("Play")}</>}</button>
              <button onClick={() => cast.stop()}><Square size={16} />{" "}{tr("Stop casting")}</button>
            </div>
          </div>
        )}
        {inIntro && !cast && (
          <button className="overlay-btn skip" onClick={() => { if (video.current) video.current.currentTime = m.intro_end!; }}>
            <FastForward size={17} />{" "}{tr("Skip intro")}</button>
        )}
        {countdown !== null && (
          <div className="overlay-next" role="status">
            <span>{tr("Next episode in")}{" "}{countdown}</span>
            <button className="primary" onClick={() => void playNext()}><SkipForward size={16} />{" "}{tr("Play now")}</button>
            <button onClick={() => { dismissedNext.current = true; setCountdown(null); }}>{tr("Keep watching")}</button>
          </div>
        )}
      </div>

      <div className="player-controls">
        <TrackMenus tracks={tracks} quality={quality} setQuality={setQuality} audio={audio} setAudio={setAudio}
          subtitle={subtitle} setSubtitle={setSubtitle} />
        {m.next_id && <button onClick={() => void playNext()}><SkipForward size={16} />{" "}{tr("Next episode")}</button>}
        <button onClick={() => { video.current?.pause(); setTogether(true); }}><PartyPopper size={16} />{" "}{tr("Watch together")}</button>
        {user.is_admin && <AiSubtitles media={m} tracks={tracks} onDone={() => api.tracks(m.id).then(setTracks).catch(() => undefined)} />}
        {!cast && <button onClick={() => void startCast()} disabled={castBusy}><Cast size={16} />{" "}{castBusy ? tr("Connecting…") : tr("Cast to TV")}</button>}
      </div>
      {castHelp && <p className="notice" role="status">{castHelp}</p>}
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
        {user.is_admin && !isEpisode && <RatingControl value={m.age} onChange={(v) => api.setMediaRating(m.id, v)} label={tr("Suitable for")} />}
        <details className="more">
          <summary><ExternalLink size={15} />{" "}{tr("Open in another player")}</summary>
          <p className="muted small">{tr("For VLC on a TV or phone: Media, Open Network Stream, then paste this address. It works for 24 hours.")}</p>
          <code>{link || "loading…"}</code>
          <button onClick={() => void navigator.clipboard?.writeText(link)} disabled={!link}>{tr("Copy address")}</button>
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
    catch (e) { setMsg(e instanceof Error ? e.message : tr("Couldn't start")); }
  };
  return (
    <section className="offline">
      <h2><Download size={17} aria-hidden />{" "}{tr("Watch without internet")}</h2>
      <p className="muted small">{tr("ZiraHive makes a smaller copy you can save on your phone or laptop. You'll get a notification when it's ready.")}</p>
      {copies.map((c) => (
        <div key={c.id} className="offline-row">
          <strong>{c.quality}</strong>
          {c.status === "ready" && <><span className="muted small">{formatBytes(c.size ?? 0)}</span>
            <a className="button primary" href={url.offlineFile(c)}><Download size={15} />{" "}{tr("Save file")}</a></>}
          {(c.status === "queued" || c.status === "working") && (
            <><div className="disk" role="progressbar" aria-valuenow={Math.round(c.progress * 100)} aria-valuemin={0} aria-valuemax={100}>
              <span style={{ width: `${c.progress * 100}%` }} /></div>
              <span className="muted small">{c.status === "queued" ? "waiting" : `${Math.round(c.progress * 100)}%`}</span></>
          )}
          {c.status === "failed" && <span className="error small">{tr("Failed:")}{" "}{c.error}</span>}
        </div>
      ))}
      <div className="inline-form">
        <label>{tr("Quality")}<select value={quality} onChange={(e) => setQuality(e.target.value)}>
            {qualities.map((q) => <option key={q} value={q}>{q}</option>)}
          </select>
        </label>
        <button onClick={() => void make()}>{tr("Make a copy")}</button>
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
        <option value="">{tr("Not rated")}</option>
        {AGE_OPTIONS.map((a) => <option key={a} value={a}>{AGE_LABEL[a]}</option>)}
      </select>
      {saved && <span className="muted small">{" "}{tr("Saved")}</span>}
    </label>
  );
}

/** For admins: subtitles made by the local AI (Whisper) from the film's speech. */
function AiSubtitles({ media, tracks, onDone }: { media: Media; tracks: Tracks; onDone: () => void }) {
  const [status, setStatus] = useState(tracks.ai_subtitles ?? null);
  const [msg, setMsg] = useState("");
  useEffect(() => { setStatus(tracks.ai_subtitles ?? null); }, [tracks]);
  useEffect(() => {
    if (status !== "queued" && status !== "working") return;
    const t = setInterval(() => {
      api.tracks(media.id).then((x) => { if (x.ai_subtitles !== status) { setStatus(x.ai_subtitles ?? null); if (x.ai_subtitles?.startsWith("done")) onDone(); } })
        .catch(() => undefined);
    }, 15_000);
    return () => clearInterval(t);
  }, [status, media.id, onDone]);
  if (status?.startsWith("done")) return null;
  const start = async () => {
    setMsg("");
    try { setStatus((await api.makeSubtitles(media.id)).status); }
    catch (e) { setMsg(e instanceof ApiError ? e.message : tr("That didn't work")); }
  };
  return (
    <span className="ai-subs">
      {status === "queued" || status === "working"
        ? <span className="muted small" role="status"><Sparkles size={15} aria-hidden />{" "}{tr("Making subtitles with AI… about as long as the film takes on a CPU.")}</span>
        : <button onClick={() => void start()} title={tr("Listens to the film and writes subtitles, on this PC")}><Sparkles size={16} />{" "}{tr("Make subtitles with AI")}</button>}
      {status?.startsWith("failed:") && <span className="error small">{" "}{tr("Last try failed: {why}", { why: status.slice(7) })}</span>}
      {msg && <span className="error small">{" "}{msg}</span>}
    </span>
  );
}
