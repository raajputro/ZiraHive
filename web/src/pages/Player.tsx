import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { api, url, formatBytes, formatDuration, type Media } from "../api";

export default function PlayerPage() {
  const { id } = useParams();
  const [m, setM] = useState<Media | null>(null);
  const [error, setError] = useState("");
  const [playError, setPlayError] = useState(false);
  const [link, setLink] = useState("");
  const video = useRef<HTMLVideoElement>(null);
  const lastSaved = useRef(0);

  useEffect(() => { if (id) api.mediaItem(id).then(setM).catch((e) => setError(e.message)); }, [id]);
  useEffect(() => { if (id) api.streamLink(id).then((r) => setLink(location.origin + r.path)).catch(() => undefined); }, [id]);

  const save = () => {
    const v = video.current;
    if (!v || !m || !v.currentTime) return;
    lastSaved.current = Date.now();
    void api.saveProgress(m.id, v.currentTime, v.duration || undefined).catch(() => undefined);
  };
  useEffect(() => {
    const onHide = () => save();
    window.addEventListener("pagehide", onHide);
    return () => { window.removeEventListener("pagehide", onHide); save(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [m]);

  if (error) return <div className="page cinema-page"><p className="error">{error}</p></div>;
  if (!m) return <div className="page cinema-page" aria-busy="true" />;

  const details = [m.year, formatDuration(m.duration), m.height ? `${m.height}p` : null,
    [m.video_codec, m.audio_codec].filter(Boolean).join(" / "), formatBytes(m.size)].filter(Boolean);

  return (
    <div className="player-page">
      <Link to="/movies" className="back"><ArrowLeft size={18} /> Movies</Link>
      <div className="player-frame">
        <video ref={video} src={url.stream(m)} controls autoPlay playsInline
          poster={m.poster_ready ? url.poster(m) : undefined}
          onLoadedMetadata={(e) => { if (m.position > 5 && !m.finished) e.currentTarget.currentTime = m.position; }}
          onTimeUpdate={() => { if (Date.now() - lastSaved.current > 10_000) save(); }}
          onPause={save} onEnded={save}
          onError={() => setPlayError(true)} />
      </div>
      <div className="player-info">
        <h1>{m.title}</h1>
        <p className="muted">{details.join(", ")}</p>
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
