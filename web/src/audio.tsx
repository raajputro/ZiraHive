import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, url, type BookDetail, type Chapter, type Track } from "./api";

import { digits, t as tr } from "./i18n";
/** One thing in the queue: a song, or one part (file) of an audiobook. */
export interface QueueItem {
  key: string;
  kind: "track" | "book";
  id: string;            // track id, or book id
  part: number;          // audiobook part index (0 for songs)
  title: string;
  subtitle: string;
  cover: string | null;
  duration: number;
  playable: boolean;     // false: the server converts it first
  link: string;          // where the title links to
  track?: Track;
}

export type Repeat = "off" | "all" | "one";
export type Sleep = { until: number } | { end: "chapter" | "track" } | null;

interface AudioCtx {
  queue: QueueItem[];
  index: number;
  current: QueueItem | null;
  book: BookDetail | null;
  playing: boolean;
  preparing: boolean;
  error: string;
  time: number;          // seconds into the current item
  duration: number;
  bookTime: number;      // seconds into the whole audiobook
  chapter: Chapter | null;
  rate: number;
  shuffle: boolean;
  repeat: Repeat;
  sleep: Sleep;
  playTracks: (tracks: Track[], start?: number, shuffled?: boolean) => void;
  playNext: (tracks: Track[]) => void;
  addToQueue: (tracks: Track[]) => void;
  playBook: (book: BookDetail, at?: number) => void;
  toggle: () => void;
  next: () => void;
  prev: () => void;
  jump: (index: number) => void;
  remove: (index: number) => void;
  seek: (seconds: number) => void;
  seekBook: (seconds: number) => void;
  skip: (seconds: number) => void;
  setRate: (rate: number) => void;
  toggleShuffle: () => void;
  cycleRepeat: () => void;
  setSleep: (s: Sleep) => void;
  close: () => void;
}

const Ctx = createContext<AudioCtx | null>(null);
export const useAudio = () => useContext(Ctx)!;

export function clock(sec: number | null | undefined): string {
  if (!sec || !isFinite(sec) || sec < 0) return digits("0:00");
  const s = Math.floor(sec % 60), m = Math.floor(sec / 60) % 60, h = Math.floor(sec / 3600);
  return digits(h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`);
}

export function trackItem(t: Track): QueueItem {
  return {
    key: `t-${t.id}-${Math.random().toString(36).slice(2, 7)}`, kind: "track", id: t.id, part: 0, title: t.title,
    subtitle: [t.artist, t.album_title].filter(Boolean).join(" · "), cover: t.cover_ready && t.album_id ? url.albumCover({ id: t.album_id }) : null,
    duration: t.duration ?? 0, playable: t.playable, link: t.album_id ? `/listen/album/${t.album_id}` : "/listen/songs", track: t,
  };
}

function bookItems(b: BookDetail): QueueItem[] {
  return b.parts.map((p) => ({
    key: `b-${b.id}-${p.index}`, kind: "book", id: b.id, part: p.index, title: b.title,
    subtitle: b.parts.length > 1 ? p.title : (b.author ?? ""), cover: b.cover_ready ? url.bookCover(b) : null,
    duration: p.duration, playable: p.playable, link: `/listen/book/${b.id}`,
  }));
}

const RATE_KEY = "zirahive.audiobookRate";
const read = (k: string) => { try { return localStorage.getItem(k); } catch { return null; } };
const write = (k: string, v: string) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } };

export function AudioProvider({ children }: { children: ReactNode }) {
  const audio = useRef<HTMLAudioElement>(null);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [index, setIndex] = useState(0);
  const [book, setBook] = useState<BookDetail | null>(null);
  const [playing, setPlaying] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [error, setError] = useState("");
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [rate, setRateState] = useState(1);
  const [shuffle, setShuffle] = useState(false);
  const [repeat, setRepeat] = useState<Repeat>("off");
  const [sleep, setSleep] = useState<Sleep>(null);
  const unshuffled = useRef<QueueItem[] | null>(null);
  const startAt = useRef(0);           // where to start the next item that loads
  const autoplay = useRef(false);
  const counted = useRef<string | null>(null);  // song whose play has been counted
  const lastSave = useRef(0);
  // files this browser failed to play: they come from the server's converted copy instead
  const fallback = useRef(new Set<string>());
  const [reload, setReload] = useState(0);
  const loadedAt = useRef(0);  // where the current item was asked to start
  const state = useRef({ queue, index, book, repeat, sleep });
  state.current = { queue, index, book, repeat, sleep };

  const current = queue[index] ?? null;
  const parts = book?.parts ?? [];
  const bookTime = current?.kind === "book" ? (parts[current.part]?.start ?? 0) + time : 0;
  const chapter = useMemo(() => {
    if (!book || current?.kind !== "book") return null;
    let found: Chapter | null = null;
    for (const c of book.chapters) if (c.start <= bookTime + 0.25) found = c;
    return found ?? book.chapters[0] ?? null;
  }, [book, current, bookTime]);

  // ---------------------------------------------------------- audiobook progress
  const saveBook = useCallback((final = false) => {
    const { book: b, queue: q, index: i } = state.current;
    const a = audio.current, item = q[i];
    if (!b || !a || item?.kind !== "book" || !b.duration) return;
    const pos = (b.parts[item.part]?.start ?? 0) + a.currentTime;
    lastSave.current = Date.now();
    void api.saveBookProgress(b.id, { position: pos, fraction: Math.min(1, pos / b.duration), finished: final || undefined }, true)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    const flush = () => { if (document.visibilityState === "hidden") saveBook(); };
    document.addEventListener("visibilitychange", flush);
    window.addEventListener("pagehide", flush);
    return () => { document.removeEventListener("visibilitychange", flush); window.removeEventListener("pagehide", flush); };
  }, [saveBook]);

  // --------------------------------------------------------------- loading items
  useEffect(() => {
    const a = audio.current;
    if (!a || !current) return;
    let cancelled = false;
    setError("");
    setTime(startAt.current);
    setDuration(current.duration);
    const forced = current.playable && fallback.current.has(`${current.kind}-${current.id}-${current.part}`);
    const src = current.kind === "track" ? url.trackStream({ id: current.id }, forced) : url.bookAudio({ id: current.id }, current.part, forced);
    const load = () => {
      if (cancelled) return;
      setPreparing(false);
      a.src = src;
      a.playbackRate = current.kind === "book" ? rate : 1;
      const at = startAt.current;
      loadedAt.current = at;
      if (at > 0) a.addEventListener("loadedmetadata", () => { a.currentTime = at; }, { once: true });
      startAt.current = 0;
      if (autoplay.current) void a.play().catch(() => setPlaying(false));
    };
    if (current.playable && !forced) load();
    else {
      // WMA, ALAC and friends: the server converts once; ask until it's ready.
      setPreparing(true);
      a.removeAttribute("src");
      a.load();
      const ask = async () => {
        if (cancelled) return;
        try {
          const r = current.kind === "track" ? await api.prepareTrack(current.id, forced)
            : await api.prepareBookPart(current.id, current.part, forced);
          if (r.ready) load();
          else if (r.failed) { setPreparing(false); setError(tr("This file couldn't be converted for the browser.")); }
          else setTimeout(() => void ask(), 1500);
        } catch { setPreparing(false); setError(tr("Couldn't reach the server.")); }
      };
      void ask();
    }
    return () => { cancelled = true; };
  // Only a different item (or a fallback) reloads; rate changes apply directly below.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current?.key, reload]);

  const onError = () => {
    const a = audio.current, item = state.current.queue[state.current.index];
    if (!a?.getAttribute("src") || !item) return;
    const id = `${item.kind}-${item.id}-${item.part}`;
    const err = a.error?.code;
    if (item.playable && !fallback.current.has(id) && (err === MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED || err === MediaError.MEDIA_ERR_DECODE)) {
      // This browser can't play this file (e.g. AAC on Linux Chromium): ask the server for an MP3.
      fallback.current.add(id);
      startAt.current = a.currentTime || loadedAt.current;
      autoplay.current = true;
      setReload((x) => x + 1);
      return;
    }
    setError(tr("This file couldn't be played."));
  };

  // ------------------------------------------------------------------ controls
  const start = (items: QueueItem[], i: number, b: BookDetail | null, at = 0) => {
    saveBook();
    unshuffled.current = null;
    setShuffle(false);
    startAt.current = at;
    autoplay.current = true;
    counted.current = null;
    setBook(b);
    setQueue(items);
    setIndex(i);
    if (items[i] && items[i].key === current?.key && audio.current) {  // same item again: just play
      audio.current.currentTime = at;
      void audio.current.play();
    }
  };

  const playTracks = (tracks: Track[], startIndex = 0, shuffled = false) => {
    const items = tracks.map(trackItem);
    setRateState(1);
    if (shuffled && items.length > 1) {
      const mixed = [...items];
      for (let i = mixed.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [mixed[i], mixed[j]] = [mixed[j], mixed[i]]; }
      start(mixed, 0, null);
      unshuffled.current = items;
      setShuffle(true);
      return;
    }
    start(items, Math.max(0, Math.min(startIndex, items.length - 1)), null);
  };

  const playBook = (b: BookDetail, at?: number) => {
    const pos = at ?? (b.progress && !b.progress.finished ? b.progress.position : 0);
    let part = 0;
    b.parts.forEach((p, i) => { if (p.start <= pos) part = i; });
    const saved = Number(read(RATE_KEY)) || 1;
    setRateState(saved);
    if (state.current.book?.id === b.id && state.current.queue[state.current.index]?.part === part && audio.current) {
      audio.current.currentTime = pos - b.parts[part].start;
      void audio.current.play();
      return;
    }
    start(bookItems(b), part, b, Math.max(0, pos - (b.parts[part]?.start ?? 0)));
  };

  const insert = (tracks: Track[], afterCurrent: boolean) => {
    if (state.current.book || !queue.length) { playTracks(tracks); return; }
    const items = tracks.map(trackItem);
    setQueue((qu) => afterCurrent ? [...qu.slice(0, index + 1), ...items, ...qu.slice(index + 1)] : [...qu, ...items]);
  };

  const go = useCallback((i: number, play = true) => {
    const { queue: qu, book: b } = state.current;
    if (i < 0 || i >= qu.length) return;
    if (b) saveBook();
    startAt.current = 0;
    autoplay.current = play;
    counted.current = null;
    setIndex(i);
  }, [saveBook]);

  const next = useCallback(() => {
    const { queue: qu, index: i, repeat: r } = state.current;
    if (i + 1 < qu.length) go(i + 1);
    else if (r === "all" && qu.length) go(0);
  }, [go]);

  const prev = () => {
    const a = audio.current;
    if (a && a.currentTime > 4) { a.currentTime = 0; return; }
    if (index > 0) go(index - 1);
    else if (a) a.currentTime = 0;
  };

  const toggle = () => {
    const a = audio.current;
    if (!a || !current) return;
    if (a.paused) { autoplay.current = true; void a.play().catch(() => undefined); }
    else a.pause();
  };

  const seek = (s: number) => { if (audio.current) audio.current.currentTime = Math.max(0, s); };

  const seekBook = (s: number) => {
    const b = state.current.book;
    if (!b) return;
    let part = 0;
    b.parts.forEach((p, i) => { if (p.start <= s + 0.01) part = i; });
    const offset = Math.max(0, s - b.parts[part].start);
    if (part === state.current.queue[state.current.index]?.part) seek(offset);
    else { saveBook(); startAt.current = offset; autoplay.current = !audio.current?.paused; setIndex(part); }
  };

  const skip = (d: number) => {
    if (state.current.book) seekBook(Math.max(0, bookTime + d));
    else seek((audio.current?.currentTime ?? 0) + d);
  };

  const setRate = (r: number) => {
    setRateState(r);
    write(RATE_KEY, String(r));
    if (audio.current && current?.kind === "book") audio.current.playbackRate = r;
  };

  const toggleShuffle = () => {
    if (shuffle) {
      // back to the original order, keeping the current item
      const orig = unshuffled.current ?? queue;
      const at = orig.findIndex((x) => x.key === current?.key);
      setQueue(orig);
      setIndex(Math.max(0, at));
      unshuffled.current = null;
      setShuffle(false);
      return;
    }
    unshuffled.current = queue;
    const rest = queue.filter((_, i) => i !== index);
    for (let i = rest.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [rest[i], rest[j]] = [rest[j], rest[i]]; }
    setQueue(current ? [current, ...rest] : rest);
    setIndex(0);
    setShuffle(true);
  };

  const cycleRepeat = () => setRepeat((r) => (r === "off" ? "all" : r === "all" ? "one" : "off"));

  const remove = (i: number) => {
    if (i === index) return;
    setQueue((qu) => qu.filter((_, j) => j !== i));
    if (i < index) setIndex((x) => x - 1);
  };

  const close = () => {
    saveBook();
    audio.current?.pause();
    audio.current?.removeAttribute("src");
    setQueue([]); setIndex(0); setBook(null); setPlaying(false); setSleep(null); setPreparing(false); setError("");
  };

  // ------------------------------------------------------------- element events
  const onTime = () => {
    const a = audio.current!;
    setTime(a.currentTime);
    const item = state.current.queue[state.current.index];
    if (!item) return;
    // count a song as played after 30 s or half of it
    if (item.kind === "track" && counted.current !== item.key && (a.currentTime > 30 || a.currentTime > (a.duration || 60) / 2)) {
      counted.current = item.key;
      void api.trackPlayed(item.id).catch(() => undefined);
    }
    if (item.kind === "book" && !a.paused && Date.now() - lastSave.current > 15_000) saveBook();
    // sleep timer
    const s = state.current.sleep;
    if (s && "until" in s && Date.now() >= s.until) { a.pause(); setSleep(null); }
    if (s && "end" in s && s.end === "chapter" && state.current.book) {
      const b = state.current.book;
      const pos = (b.parts[item.part]?.start ?? 0) + a.currentTime;
      const nextCh = b.chapters.find((c) => c.start > (sleepFrom.current ?? 0) + 1);
      if (nextCh && pos >= nextCh.start) { a.pause(); setSleep(null); }
    }
  };
  const sleepFrom = useRef<number | null>(null);
  useEffect(() => { sleepFrom.current = sleep && "end" in sleep ? bookTime : null; },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [sleep]);

  const onEnded = () => {
    const { queue: qu, index: i, repeat: r, sleep: s, book: b } = state.current;
    const a = audio.current!;
    if (s && "end" in s) { setSleep(null); if (!b || i + 1 >= qu.length) { setPlaying(false); return; } }
    if (!b && r === "one") { a.currentTime = 0; void a.play(); return; }
    if (i + 1 < qu.length) { go(i + 1, !(s && "end" in s)); return; }
    if (!b && r === "all" && qu.length) { go(0); return; }
    if (b) saveBook(true);
    setPlaying(false);
  };

  // ---------------------------------------------------- lock screen and headsets
  useEffect(() => {
    if (!("mediaSession" in navigator)) return;
    const ms = navigator.mediaSession;
    if (!current) { ms.metadata = null; return; }
    ms.metadata = new MediaMetadata({
      title: current.kind === "book" && chapter ? chapter.title : current.title,
      artist: current.kind === "book" ? (book?.author ?? "") : (current.track?.artist ?? ""),
      album: current.kind === "book" ? current.title : (current.track?.album_title ?? ""),
      artwork: current.cover ? [{ src: new URL(current.cover, location.href).href, sizes: "600x600", type: "image/webp" }] : [],
    });
  }, [current, chapter, book]);

  const handlers = useRef({ toggle, next, prev, skip, seek });
  handlers.current = { toggle, next, prev, skip, seek };
  useEffect(() => {
    if (!("mediaSession" in navigator)) return;
    const ms = navigator.mediaSession;
    const set = (action: MediaSessionAction, fn: MediaSessionActionHandler | null) => { try { ms.setActionHandler(action, fn); } catch { /* unsupported */ } };
    set("play", () => handlers.current.toggle());
    set("pause", () => handlers.current.toggle());
    set("nexttrack", () => handlers.current.next());
    set("previoustrack", () => handlers.current.prev());
    set("seekbackward", (d) => handlers.current.skip(-(d.seekOffset || 15)));
    set("seekforward", (d) => handlers.current.skip(d.seekOffset || 30));
    set("seekto", (d) => { if (d.seekTime !== undefined) handlers.current.seek(d.seekTime); });
  }, []);

  useEffect(() => {
    if ("mediaSession" in navigator) navigator.mediaSession.playbackState = current ? (playing ? "playing" : "paused") : "none";
  }, [playing, current]);

  const value: AudioCtx = {
    queue, index, current, book, playing, preparing, error, time, duration, bookTime, chapter, rate, shuffle, repeat, sleep,
    playTracks, playNext: (t) => insert(t, true), addToQueue: (t) => insert(t, false), playBook, toggle, next, prev,
    jump: (i) => go(i), remove, seek, seekBook, skip, setRate, toggleShuffle, cycleRepeat, setSleep, close,
  };

  return (
    <Ctx.Provider value={value}>
      {children}
      <audio ref={audio} preload="auto" onTimeUpdate={onTime} onEnded={onEnded}
        onPlay={() => setPlaying(true)} onPause={() => { setPlaying(false); saveBook(); }}
        onDurationChange={() => { const d = audio.current?.duration; if (d && isFinite(d)) setDuration(d); }}
        onError={onError} />
    </Ctx.Provider>
  );
}
