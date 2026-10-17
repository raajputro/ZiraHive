// Chromecast: Google's Cast library, loaded only when someone presses Cast.
// The Chromecast fetches the video itself, from ZiraHive's home-network address, using links
// that work only for that one title (see GET /api/media/{id}/cast).
/* eslint-disable @typescript-eslint/no-explicit-any */
import type { CastInfo } from "./api";

const SDK = "https://www.gstatic.com/cv/js/sender/v1/cast_sender.js?loadCastFramework=1";
let loading: Promise<boolean> | null = null;

declare global {
  interface Window { __onGCastApiAvailable?: (ok: boolean) => void; cast?: any; chrome?: any }
}

/** Why casting can't work in this browser, or null when it can be tried. */
export function castProblem(): string | null {
  if (!window.isSecureContext) return "insecure";
  if (!/Chrome|CriOS|Edg\//.test(navigator.userAgent) || /Firefox|FxiOS/.test(navigator.userAgent)) return "browser";
  return null;
}

export function loadCast(): Promise<boolean> {
  if (window.cast?.framework) return Promise.resolve(true);
  if (loading) return loading;
  loading = new Promise<boolean>((resolve) => {
    const timer = setTimeout(() => resolve(false), 10_000);
    window.__onGCastApiAvailable = (ok) => {
      clearTimeout(timer);
      if (ok && window.cast?.framework) {
        window.cast.framework.CastContext.getInstance().setOptions({
          receiverApplicationId: window.chrome.cast.media.DEFAULT_MEDIA_RECEIVER_APP_ID,
          autoJoinPolicy: window.chrome.cast.AutoJoinPolicy.ORIGIN_SCOPED,
        });
      }
      resolve(ok && !!window.cast?.framework);
    };
    const s = document.createElement("script");
    s.src = SDK;
    s.async = true;
    s.onerror = () => { clearTimeout(timer); resolve(false); };
    document.head.appendChild(s);
  });
  loading.then((ok) => { if (!ok) loading = null; });
  return loading;
}

export interface CastState { device: string; playing: boolean; time: number; duration: number }

export interface CastControl {
  playPause(): void;
  seek(seconds: number): void;
  stop(): void;
  /** Called with the state whenever it changes; returns the unsubscribe function. */
  watch(cb: (s: CastState | null) => void): () => void;
}

/** Opens the device picker, then plays `info` on the chosen Chromecast. */
export async function castTo(info: CastInfo, subtitleId: string): Promise<CastControl> {
  const c = window.chrome.cast, f = window.cast.framework;
  const ctx = f.CastContext.getInstance();
  if (!ctx.getCurrentSession()) await ctx.requestSession();  // the browser's device list
  const session = ctx.getCurrentSession();
  if (!session) throw new Error("cancelled");

  const media = new c.media.MediaInfo(info.url, info.content_type);
  media.streamType = c.media.StreamType.BUFFERED;
  if (info.converted) {
    media.hlsSegmentFormat = c.media.HlsSegmentFormat.TS;
    media.hlsVideoSegmentFormat = c.media.HlsVideoSegmentFormat.MPEG2_TS;
  }
  if (info.duration) media.duration = info.duration;
  const meta = new c.media.GenericMediaMetadata();
  meta.title = info.title;
  if (info.subtitle) meta.subtitle = info.subtitle;
  if (info.poster) meta.images = [new c.Image(info.poster)];
  media.metadata = meta;
  media.tracks = info.subtitles.map((s, i) => {
    const t = new c.media.Track(i + 1, c.media.TrackType.TEXT);
    t.trackContentId = s.url;
    t.trackContentType = "text/vtt";
    t.subtype = c.media.TextTrackType.SUBTITLES;
    t.name = s.label;
    if (s.language) t.language = s.language;
    return t;
  });
  const request = new c.media.LoadRequest(media);
  request.currentTime = info.start;
  request.autoplay = true;
  const chosen = info.subtitles.findIndex((s) => s.url.includes(`/subtitles/${subtitleId}.vtt?`));
  if (chosen >= 0) request.activeTrackIds = [chosen + 1];
  const error = await session.loadMedia(request);
  if (error) throw new Error(String(error));

  const player = new f.RemotePlayer();
  const controller = new f.RemotePlayerController(player);
  const device = session.getCastDevice()?.friendlyName || "Chromecast";
  return {
    playPause: () => controller.playOrPause(),
    seek: (s) => { player.currentTime = s; controller.seek(); },
    stop: () => ctx.endCurrentSession(true),
    watch(cb) {
      const send = () => cb(player.isConnected
        ? { device, playing: !player.isPaused, time: player.currentTime || 0, duration: player.duration || info.duration || 0 }
        : null);
      controller.addEventListener(f.RemotePlayerEventType.ANY_CHANGE, send);
      send();
      return () => controller.removeEventListener(f.RemotePlayerEventType.ANY_CHANGE, send);
    },
  };
}
