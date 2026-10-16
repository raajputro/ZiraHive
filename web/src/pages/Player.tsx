import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, SkipForward } from "lucide-react";
import { api, url, episodeCode, formatBytes, formatDuration, type Media } from "../api";

// Remount for every title so progress is always saved against the right one.
export default function PlayerRoute() {
  const { id } = useParams();
  return id ? <Player key={id} id={id} /> : null;
}

function Player({ id }: { id: string }) {
  const navigate = useNavigate();
  const [m, setM] = useState<Media | null>(null);
  const [error, setError] = useState("");
  const [playError, setPlayError] = useState(false);
  const [link, setLink] = useState("");
  const video = useRef<HTMLVideoElement>(null);
  const lastSaved = useRef(0);

  useEffect(() => { api.mediaItem(id).then(setM).catch((e) => setError(e.message)); }, [id]);
  useEffect(() => { api.streamLink(id).then((r) => setLink(location.origin + r.path)).catch(() => undefined); }, [id]);

  const save = () => {
    const v = video.current;
    if (!v || !m || !v.currentTime) return Promise.resolve();
    lastSaved.current = Date.now();
    return api.saveProgress(m.id, v.currentTime, v.duration || undefined).catch(() => undefined);
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

  if (error) return <div className="page cinema-page"><p className="error">{error}</p></div>;
  if (!m) return <div className="page cinema-page" aria-busy="true" />;

  const isEpisode = !!m.series_id;
  const details = [!isEpisode && m.year, formatDuration(m.duration), m.height ? `${m.height}p` : null,
    [m.video_codec, m.audio_codec].filter(Boolean).join(" / "), formatBytes(m.size)].filter(Boolean);

  return (
    <div className="player-page">
      {isEpisode
        ? <Link to={`/watch/series/${m.series_id}`} className="back"><ArrowLeft size={18} /> {m.series_title}</Link>
        : <Link to={`/watch/c/${m.library_id}`} className="back"><ArrowLeft size={18} /> Back</Link>}
      <div className="player-frame">
        <video ref={video} src={url.stream(m)} controls autoPlay playsInline
          poster={m.poster_ready ? url.poster(m) : undefined}
          onLoadedMetadata={(e) => { if (m.position > 5 && !m.finished) e.currentTarget.currentTime = m.position; }}
          onTimeUpdate={() => { if (Date.now() - lastSaved.current > 10_000) void save(); }}
          onPause={() => void save()}
          onEnded={() => { if (m.next_id) void playNext(); else void save(); }}
          onError={() => setPlayError(true)} />
      </div>
      <div className="player-info">
        {isEpisode ? (
          <>
            <p className="episode-code">{m.series_title}, {episodeCode(m)}</p>
            <h1>{m.episode_title ?? m.title}</h1>
          </>
        ) : <h1>{m.title}</h1>}
        <p className="muted">{details.join(", ")}</p>
        {m.next_id && (
          <button className="primary" onClick={() => void playNext()}><SkipForward size={17} /> Next episode</button>
        )}
        {(!m.browser_playable || playError) && (
          <p className="notice">
            This file uses a format browsers can't always play ({[m.container, m.video_codec, m.audio_codec].filter(Boolean).join(", ")}).
            If it doesn't start, open it in VLC (Media, Open Network Stream) with this address, valid for 24 hours:
            <code>{link || "loading…"}</code>
            <button onClick={() => void navigator.clipboard?.writeText(link)} disabled={!link}>Copy address</button>
          </p>
        )}
        {m.overview && <p className="overview">{m.overview}</p>}
      </div>
    </div>
  );
}
