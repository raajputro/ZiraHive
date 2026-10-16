import { useEffect, useRef, type MutableRefObject, type RefObject } from "react";
import Hls from "hls.js";
import { url, type Media, type Quality, type Tracks } from "./api";

export const QUALITY_LABEL: Record<Quality, string> = {
  original: "Original", "1080p": "1080p", "720p": "720p", "480p": "480p (saves data)", "360p": "360p (lowest data)",
};

/** Low-data mode starts at 480p; otherwise play the file as it is when the browser can. */
export function defaultQuality(t: Tracks, lowData: boolean): Quality {
  const small = t.qualities.find((q) => q === "480p") ?? t.qualities[t.qualities.length - 1];
  return lowData ? small : t.direct_play ? "original" : t.qualities[0];
}

export const defaultAudio = (t: Tracks) => t.audio.find((a) => a.default)?.index ?? 0;

/**
 * Loads a title into a <video>: the original file when the browser can play it, otherwise the
 * converted HLS stream (hls.js, or Safari's own player). Reloads when quality or audio changes,
 * keeping the position. `startAt` (if set) is used once for the next load.
 */
export function useVideoSource(video: RefObject<HTMLVideoElement>, opts: {
  media: Media | null; tracks: Tracks | null; quality: Quality | null; audio: number;
  startAt: MutableRefObject<number | null>; autoplay: boolean; onError: (msg: string) => void;
}) {
  const { media, tracks, quality, audio } = opts;
  const hls = useRef<Hls | null>(null);
  const latest = useRef(opts);
  latest.current = opts;

  useEffect(() => {
    const v = video.current;
    if (!v || !media || !tracks || !quality) return;
    const at = latest.current.startAt.current ?? (v.currentTime > 0 ? v.currentTime : 0);
    latest.current.startAt.current = null;
    hls.current?.destroy();
    hls.current = null;
    const direct = quality === "original" && tracks.direct_play && audio === defaultAudio(tracks);
    const resume = () => { if (at > 0) v.currentTime = at; };
    if (direct) {
      v.src = url.stream(media);
      v.addEventListener("loadedmetadata", resume, { once: true });
    } else {
      const q = quality === "original" ? tracks.qualities[0] : quality;
      const src = url.hls(media, q, audio);
      if (Hls.isSupported()) {
        const h = new Hls({ startPosition: at, maxBufferLength: 30, xhrSetup: (xhr) => { xhr.withCredentials = true; } });
        h.loadSource(src);
        h.attachMedia(v);
        h.on(Hls.Events.ERROR, (_e, data) => {
          console.warn("video stream:", data.type, data.details, data.fatal ? "(fatal)" : "", data.error?.message ?? "");
          if (!data.fatal) return;
          const onError = latest.current.onError;
          if (data.response?.code === 503) onError("The server is busy converting other videos. Try again in a minute, or choose Original.");
          else if (String(data.details).toLowerCase().includes("codec")) onError("This browser can't play H.264 video. Use Chrome, Edge, Firefox or Safari.");
          else onError("This video couldn't be converted. Try another quality.");
        });
        hls.current = h;
      } else {
        v.src = src;  // Safari plays HLS itself
        v.addEventListener("loadedmetadata", resume, { once: true });
      }
    }
    if (latest.current.autoplay) void v.play().catch(() => undefined);
    return () => { hls.current?.destroy(); hls.current = null; };
  }, [video, media, tracks, quality, audio]);
}

/** Shows the chosen subtitle track (or none). */
export function useSubtitle(video: RefObject<HTMLVideoElement>, subtitle: string, deps: unknown[]) {
  useEffect(() => {
    const v = video.current;
    if (!v) return;
    for (const t of Array.from(v.textTracks)) t.mode = t.id === subtitle ? "showing" : "disabled";
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [subtitle, ...deps]);
}

export function SubtitleTracks({ media, tracks }: { media: Media; tracks: Tracks }) {
  return (
    <>
      {tracks.subtitles.filter((s) => s.usable).map((s) => (
        <track key={s.id} id={s.id} kind="subtitles" label={s.label} srcLang={s.language ?? undefined} src={url.subtitle(media, s.id)} />
      ))}
    </>
  );
}

/** Quality, audio and subtitle menus. */
export function TrackMenus({ tracks, quality, setQuality, audio, setAudio, subtitle, setSubtitle }: {
  tracks: Tracks; quality: Quality; setQuality: (q: Quality) => void; audio: number; setAudio: (a: number) => void;
  subtitle: string; setSubtitle: (s: string) => void;
}) {
  const qualities: Quality[] = [...(tracks.direct_play ? ["original" as Quality] : []), ...tracks.qualities];
  return (
    <>
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
    </>
  );
}
