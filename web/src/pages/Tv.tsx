// Live TV: an IPTV subscription (Xtream Codes) with channels and a programme guide, movies and
// series, laid out like Televizo / IPTV Smarters. Video always comes through the ZiraHive server.
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type FormEvent, type ReactNode } from "react";
import { nativeApp, onPlayerClosed } from "../native";
import { Link, NavLink, Navigate, useNavigate, useParams, useSearchParams } from "react-router-dom";
import Hls from "hls.js";
import { ChevronLeft, Maximize, Pencil, Play, Plus, RefreshCw, Search, Settings2, Star, Trash2 } from "lucide-react";
import {
  ApiError, formatDuration, iptvApi, type IptvAccount, type IptvCategory, type IptvEpg, type IptvEpisode, type IptvFavorite,
  type IptvItem, type IptvKind, type IptvMovie, type IptvPlay, type IptvSeries, type IptvSource, type IptvStreamKind,
} from "../api";
import { useAuth } from "../App";
import { digits, locale, t as tr, tx } from "../i18n";

// ------------------------------------------------------------------ helpers

const VIEWER = (() => {
  const make = () => Math.random().toString(36).slice(2, 12).padEnd(8, "0");
  try {
    let v = sessionStorage.getItem("zirahive.tv.viewer");
    if (!v) { v = make(); sessionStorage.setItem("zirahive.tv.viewer", v); }
    return v;
  } catch { return make(); }
})();

const withViewer = (u: string) => `${u}${u.includes("?") ? "&" : "?"}v=${VIEWER}`;

/** Tell the server this screen stopped watching, so the provider connection is freed at once. */
function stopWatching() {
  void fetch("/api/iptv/stop", {
    method: "POST", keepalive: true, credentials: "same-origin",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify({ v: VIEWER }),
  }).catch(() => undefined);
}

function load<T>(key: string, fallback: T): T {
  try { const raw = localStorage.getItem(key); return raw ? (JSON.parse(raw) as T) : fallback; } catch { return fallback; }
}
function save(key: string, value: unknown) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode */ }
}

const timeOf = (iso: string | null) =>
  iso ? new Date(iso).toLocaleTimeString(locale(), { hour: "numeric", minute: "2-digit" }) : "";

const errorText = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback);

/**
 * Plays an HLS address in a <video> (hls.js, or Safari's own player). `onFatal` gets whether it
 * looks like a picture/sound format problem (worth converting) and the server's message, if any.
 */
function playHls(v: HTMLVideoElement, src: string, opts: { startAt?: number; onFatal: (codec: boolean, message: string | null) => void }) {
  if (Hls.isSupported()) {
    const h = new Hls({
      startPosition: opts.startAt ?? -1, maxBufferLength: 30, liveSyncDurationCount: 3,
      manifestLoadingTimeOut: 45000, manifestLoadingMaxRetry: 1,
      xhrSetup: (xhr) => { xhr.withCredentials = true; },
    });
    h.loadSource(src);
    h.attachMedia(v);
    h.on(Hls.Events.ERROR, (_e, data) => {
      if (!data.fatal) return;
      let message: string | null = null;
      try {
        const xhr = data.networkDetails as XMLHttpRequest | undefined;
        const body = JSON.parse(xhr?.responseText ?? "");
        if (typeof body.detail === "string") message = tx(body.detail);
      } catch { /* not JSON */ }
      const codec = data.type === Hls.ErrorTypes.MEDIA_ERROR || String(data.details).toLowerCase().includes("codec");
      opts.onFatal(codec, message);
    });
    void v.play().catch(() => undefined);
    return () => h.destroy();
  }
  const onError = () => opts.onFatal(true, null);
  v.addEventListener("error", onError);
  v.src = src;
  if (opts.startAt) v.addEventListener("loadedmetadata", () => { v.currentTime = opts.startAt ?? 0; }, { once: true });
  void v.play().catch(() => undefined);
  return () => { v.removeEventListener("error", onError); v.removeAttribute("src"); v.load(); };
}

function fullscreen(el: HTMLElement | null) {
  if (!el) return;
  if (document.fullscreenElement) void document.exitFullscreen();
  else void el.requestFullscreen?.().catch(() => undefined);
}

function useSources() {
  const [sources, setSources] = useState<IptvSource[] | null>(null);
  const [error, setError] = useState("");
  const reload = useCallback(() => {
    iptvApi.sources().then(setSources).catch((e) => { setError(errorText(e, tr("Can't reach the server."))); setSources([]); });
  }, []);
  useEffect(reload, [reload]);
  return { sources, error, reload };
}

function useFavorites(source: string) {
  const [favs, setFavs] = useState<IptvFavorite[]>([]);
  useEffect(() => { iptvApi.favorites(source).then(setFavs).catch(() => undefined); }, [source]);
  const find = (kind: IptvKind, id: string) => favs.find((f) => f.kind === kind && f.stream_id === id);
  const toggle = async (kind: IptvKind, item: { id: string; name: string; icon: string | null; ext?: string | null }) => {
    const existing = find(kind, item.id);
    if (existing) {
      await iptvApi.removeFavorite(existing.id).catch(() => undefined);
      setFavs((f) => f.filter((x) => x.id !== existing.id));
    } else {
      const added = await iptvApi.addFavorite({ source_id: source, kind, stream_id: item.id, name: item.name, icon: item.icon, ext: item.ext ?? null })
        .catch(() => null);
      if (added) setFavs((f) => [...f, added]);
    }
  };
  return { favs, isFav: (kind: IptvKind, id: string) => !!find(kind, id), toggle };
}

function StarButton({ on, onClick }: { on: boolean; onClick: () => void }) {
  return (
    <button className={`icon tv-star${on ? " on" : ""}`} onClick={onClick} aria-pressed={on}
      title={on ? tr("Remove from favourites") : tr("Add to favourites")} aria-label={on ? tr("Remove from favourites") : tr("Add to favourites")}>
      <Star size={18} fill={on ? "currentColor" : "none"} />
    </button>
  );
}

function Logo({ src, name, className }: { src: string | null | undefined; name: string; className: string }) {
  const [broken, setBroken] = useState(false);
  if (!src || broken) return <span className={`${className} blank`} aria-hidden>{name.slice(0, 2).toUpperCase()}</span>;
  return <img className={className} src={src} alt="" loading="lazy" onError={() => setBroken(true)} />;
}

// ------------------------------------------------------------------ pages

/** /tv: the first source's channels, or the set-up form when there's none yet. */
export function TvHome() {
  const { sources, error } = useSources();
  if (!sources) return <div className="tv-page" aria-busy="true" />;
  if (sources.length === 0) {
    return (
      <div className="tv-page">
        <div className="tv-welcome">
          <h1>{tr("Live TV")}</h1>
          <p className="muted">{tr("Add your IPTV subscription (Xtream Codes) to watch live channels, movies and series here. Your provider gives you a server address, a username and a password.")}</p>
          {error && <p className="error" role="alert">{error}</p>}
          <SourceForm />
        </div>
      </div>
    );
  }
  const last = load<string | null>("zirahive.tv.source", null);
  const pick = sources.find((s) => s.id === last) ?? sources[0];
  return <Navigate to={`/tv/${pick.id}/live`} replace />;
}

const TABS: { tab: string; label: string }[] = [
  { tab: "live", label: "Live TV" }, { tab: "movies", label: "Movies" }, { tab: "series", label: "Series" }, { tab: "favorites", label: "Favourites" },
];

function TvBar({ source, sources }: { source: string; sources: IptvSource[] }) {
  const navigate = useNavigate();
  const { tab = "live" } = useParams();
  const here = TABS.some((x) => x.tab === tab) ? tab : "live";
  return (
    <div className="tv-bar">
      {sources.length > 1 ? (
        <select value={source} onChange={(e) => navigate(`/tv/${e.target.value}/${here}`)} aria-label={tr("IPTV source")}>
          {sources.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      ) : <strong className="tv-name">{sources.find((s) => s.id === source)?.name}</strong>}
      <nav className="lib-tabs" aria-label={tr("Live TV sections")}>
        {TABS.map((x) => <NavLink key={x.tab} to={`/tv/${source}/${x.tab}`}>{tr(x.label)}</NavLink>)}
      </nav>
      <Link to="/tv/sources" className="icon" title={tr("IPTV sources")} aria-label={tr("IPTV sources")}><Settings2 size={19} /></Link>
    </div>
  );
}

/** /tv/:source/:tab */
export function TvPage() {
  const { source = "", tab = "live" } = useParams();
  const { sources } = useSources();
  useEffect(() => { if (source) save("zirahive.tv.source", source); }, [source]);
  if (!sources) return <div className="tv-page" aria-busy="true" />;
  if (!sources.some((s) => s.id === source)) return <Navigate to="/tv" replace />;
  return (
    <div className="tv-page">
      <TvBar source={source} sources={sources} />
      {tab === "live" && <LiveTab key={source} source={source} />}
      {tab === "movies" && <GridTab key={`${source}-vod`} source={source} kind="vod" />}
      {tab === "series" && <GridTab key={`${source}-series`} source={source} kind="series" />}
      {tab === "favorites" && <FavoritesTab key={source} source={source} />}
    </div>
  );
}

function Categories({ cats, value, onChange, allCount }: { cats: IptvCategory[] | null; value: string; onChange: (id: string) => void; allCount?: number }) {
  return (
    <>
      <div className="tv-col tv-cats tv-cats-col" role="listbox" aria-label={tr("Categories")}>
        <button className={value === "" ? "on" : ""} onClick={() => onChange("")} role="option" aria-selected={value === ""}>
          <span>{tr("All")}</span>{allCount !== undefined && <span className="count">{digits(String(allCount))}</span>}
        </button>
        {cats?.map((c) => (
          <button key={c.id} className={value === c.id ? "on" : ""} onClick={() => onChange(c.id)} role="option" aria-selected={value === c.id}>
            <span>{c.name}</span><span className="count">{digits(String(c.count))}</span>
          </button>
        ))}
        {cats === null && <p className="muted tv-pad">{tr("Loading…")}</p>}
      </div>
      <select className="tv-mobile-cats" value={value} onChange={(e) => onChange(e.target.value)} aria-label={tr("Category")}>
        <option value="">{tr("All")}</option>
        {cats?.map((c) => <option key={c.id} value={c.id}>{c.name} ({digits(String(c.count))})</option>)}
      </select>
    </>
  );
}

// ------------------------------------------------------------------ live TV

const PAGE = 300;

function LiveTab({ source }: { source: string }) {
  const [params, setParams] = useSearchParams();
  const category = params.get("c") ?? load<string>(`zirahive.tv.cat.${source}`, "");
  const [cats, setCats] = useState<IptvCategory[] | null>(null);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState<{ total: number; items: IptvItem[] } | null>(null);
  const [error, setError] = useState("");
  const [channel, setChannel] = useState<IptvItem | null>(() => {
    const ch = params.get("ch");
    if (ch) return { id: ch, name: params.get("n") ?? ch, icon: params.get("i"), category_id: null };
    return load<IptvItem | null>(`zirahive.tv.last.${source}`, null);
  });
  const fav = useFavorites(source);
  const list = useRef<HTMLDivElement>(null);

  useEffect(() => { iptvApi.categories(source, "live").then(setCats).catch((e) => { setCats([]); setError(errorText(e, tr("Can't load the channels."))); }); }, [source]);
  useEffect(() => {
    let alive = true;
    const t = window.setTimeout(() => {
      iptvApi.items(source, { kind: "live", category: category || undefined, q: query || undefined, limit: PAGE })
        .then((p) => { if (alive) { setPage(p); setError(""); } })
        .catch((e) => { if (alive) { setPage({ total: 0, items: [] }); setError(errorText(e, tr("Can't load the channels."))); } });
    }, query ? 250 : 0);
    return () => { alive = false; window.clearTimeout(t); };
  }, [source, category, query]);

  const choose = (item: IptvItem) => {
    setChannel(item);
    save(`zirahive.tv.last.${source}`, item);
    if (params.get("ch")) { params.delete("ch"); params.delete("n"); params.delete("i"); setParams(params, { replace: true }); }
  };
  const setCategory = (c: string) => {
    save(`zirahive.tv.cat.${source}`, c);
    params.set("c", c);
    setParams(params, { replace: true });
  };
  const more = () => {
    if (!page) return;
    iptvApi.items(source, { kind: "live", category: category || undefined, q: query || undefined, offset: page.items.length, limit: PAGE })
      .then((p) => setPage({ total: p.total, items: [...page.items, ...p.items] })).catch(() => undefined);
  };
  /** Up / down (or channel up / down on a TV remote) zaps through the list. */
  const zap = (step: number) => {
    const items = page?.items ?? [];
    if (!items.length) return;
    const at = channel ? items.findIndex((i) => i.id === channel.id) : -1;
    const next = items[(at + step + items.length) % items.length];
    choose(next);
    list.current?.querySelector<HTMLElement>(`[data-ch="${CSS.escape(next.id)}"]`)?.scrollIntoView({ block: "nearest" });
  };
  // Listen on the whole window: after a click (or on a TV remote) focus is usually on <body>,
  // not inside this page, so a handler on the page's own element would never see the keys.
  const zapRef = useRef(zap);
  zapRef.current = zap;
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
      const el = e.target as HTMLElement | null;
      if (el && (el.isContentEditable || ["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName))) return;
      if (document.querySelector("dialog[open], [role='dialog']")) return;
      if (e.key === "ArrowDown" || e.key === "PageDown" || e.key === "ChannelDown") { e.preventDefault(); zapRef.current(1); }
      if (e.key === "ArrowUp" || e.key === "PageUp" || e.key === "ChannelUp") { e.preventDefault(); zapRef.current(-1); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const allCount = cats?.reduce((n, c) => n + c.count, 0);

  return (
    <div className="tv-live">
      <Categories cats={cats} value={category} onChange={setCategory} allCount={allCount} />
      <div className="tv-col tv-channels" ref={list}>
        <label className="search tv-search">
          <Search size={16} aria-hidden />
          <input placeholder={tr("Search channels")} value={query} onChange={(e) => setQuery(e.target.value)} aria-label={tr("Search channels")} />
        </label>
        {error && <p className="error tv-pad" role="alert">{error}</p>}
        {page === null && <p className="muted tv-pad">{tr("Loading…")}</p>}
        {page && page.items.length === 0 && !error && <p className="muted tv-pad">{tr("No channels here.")}</p>}
        {page?.items.map((c) => (
          <button key={c.id} data-ch={c.id} className={`ch${channel?.id === c.id ? " on" : ""}`} onClick={() => choose(c)}
            aria-current={channel?.id === c.id ? "true" : undefined}>
            <span className="ch-num">{c.num != null ? digits(String(c.num)) : ""}</span>
            <Logo src={c.icon} name={c.name} className="ch-logo" />
            <span className="ch-name">{c.name}</span>
            {fav.isFav("live", c.id) && <Star size={13} className="ch-fav" fill="currentColor" aria-label={tr("Favourite")} />}
          </button>
        ))}
        {page && page.items.length < page.total && <button className="tv-more" onClick={more}>{tr("Show more ({n} left)", { n: page.total - page.items.length })}</button>}
      </div>
      <LivePlayer source={source} channel={channel} isFav={channel ? fav.isFav("live", channel.id) : false}
        onFav={() => channel && void fav.toggle("live", channel)} onZap={zap} />
    </div>
  );
}

function LivePlayer({ source, channel, isFav, onFav, onZap }: {
  source: string; channel: IptvItem | null; isFav: boolean; onFav: () => void; onZap: (step: number) => void;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const frame = useRef<HTMLDivElement>(null);
  // "convert" is remembered per channel: some channels always need it
  const [override, setOverride] = useState<{ id: string; on: boolean } | null>(null);
  const convertKey = `zirahive.tv.convert.${source}.${channel?.id}`;
  const convert = channel ? (override?.id === channel.id ? override.on : load<boolean>(convertKey, false)) : false;
  const setConvert = (on: boolean) => { if (channel) setOverride({ id: channel.id, on }); };
  const [attempt, setAttempt] = useState(0);
  const [status, setStatus] = useState<"idle" | "tuning" | "playing" | "error" | "native">("idle");
  const [message, setMessage] = useState("");
  const [epg, setEpg] = useState<IptvEpg[]>([]);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const v = video.current;
    if (!v || !channel) return;
    setStatus("tuning");
    setMessage("");
    if (nativeApp) {  // in the Android app: the phone's player (handles more channel formats)
      const live = (mode: string) => withViewer(`/api/iptv/sources/${source}/ch/live/${encodeURIComponent(channel.id)}/${mode}/index.m3u8`);
      nativeApp.play({ url: live(convert ? "convert" : "copy"), fallbackUrl: convert ? undefined : live("convert"),
        title: channel.name, poster: channel.icon, live: true, key: "tv-live" });
      setStatus("native");
      return;
    }
    const onPlaying = () => setStatus("playing");
    v.addEventListener("playing", onPlaying);
    const src = `/api/iptv/sources/${source}/ch/live/${encodeURIComponent(channel.id)}/${convert ? "convert" : "copy"}/index.m3u8`;
    // Sound but no picture after a while: the channel's video format isn't one browsers play.
    const check = window.setTimeout(() => {
      if (!convert && v.readyState >= 2 && v.videoWidth === 0) setConvert(true);
    }, 9000);
    const stop = playHls(v, withViewer(src), {
      onFatal: (codec, msg) => {
        if (codec && !convert) { setConvert(true); return; }
        setStatus("error");
        setMessage(msg ?? tr("This channel couldn't be played right now."));
      },
    });
    return () => { window.clearTimeout(check); v.removeEventListener("playing", onPlaying); stop(); };
  }, [source, channel, convert, attempt]);

  useEffect(() => {
    const leave = () => stopWatching();
    window.addEventListener("pagehide", leave);
    return () => { window.removeEventListener("pagehide", leave); leave(); };
  }, []);
  // the app's player closed: free the provider connection
  useEffect(() => onPlayerClosed((r) => { if (r.key === "tv-live") stopWatching(); }), []);

  useEffect(() => {
    setEpg([]);
    if (!channel) return;
    let alive = true;
    const get = () => iptvApi.epg(source, channel.id).then((e) => alive && setEpg(e)).catch(() => undefined);
    void get();
    const timer = window.setInterval(() => { setNow(Date.now()); void get(); }, 60000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [source, channel]);

  const toggleConvert = () => {
    save(convertKey, !convert);
    setConvert(!convert);
  };
  const current = epg.find((e) => e.start && e.end && Date.parse(e.start) <= now && now < Date.parse(e.end));
  const upcoming = epg.filter((e) => e.start && Date.parse(e.start) > now).slice(0, 4);
  const pct = current?.start && current.end
    ? Math.min(100, ((now - Date.parse(current.start)) / (Date.parse(current.end) - Date.parse(current.start))) * 100) : 0;

  return (
    <div className="tv-player">
      <div className="player-frame tv-frame" ref={frame}>
        <video ref={video} controls playsInline autoPlay onDoubleClick={() => fullscreen(frame.current)} />
        {!channel && <div className="tv-overlay">{tr("Pick a channel")}</div>}
        {channel && status === "tuning" && <div className="tv-overlay">{tr("Tuning in to {name}…", { name: channel.name })}</div>}
        {channel && status === "native" && (
          <div className="tv-overlay">
            <p>{tr("Playing in the ZiraHive player.")}</p>
            <button onClick={() => setAttempt((a) => a + 1)}>{tr("Play")}</button>
          </div>
        )}
        {channel && status === "error" && (
          <div className="tv-overlay error" role="alert">
            <p>{message}</p>
            <button onClick={() => setAttempt((a) => a + 1)}><RefreshCw size={15} aria-hidden />{" "}{tr("Try again")}</button>
          </div>
        )}
      </div>
      {channel && (
        <>
          <div className="tv-now">
            <Logo src={channel.icon} name={channel.name} className="ch-logo big" />
            <h2>{channel.name}</h2>
            <button className="icon" onClick={() => onZap(-1)} title={tr("Previous channel")} aria-label={tr("Previous channel")}>▲</button>
            <button className="icon" onClick={() => onZap(1)} title={tr("Next channel")} aria-label={tr("Next channel")}>▼</button>
            <StarButton on={isFav} onClick={onFav} />
            <button className={`icon${convert ? " on" : ""}`} onClick={toggleConvert} aria-pressed={convert}
              title={tr("Convert the picture (for channels that show sound but no picture)")} aria-label={tr("Convert the picture")}>
              <RefreshCw size={18} />
            </button>
            <button className="icon" onClick={() => fullscreen(frame.current)} title={tr("Full screen")} aria-label={tr("Full screen")}><Maximize size={18} /></button>
          </div>
          {epg.length > 0 ? (
            <ul className="tv-epg">
              {current && (
                <li className="now">
                  <span className="time">{tr("Now")} · {timeOf(current.start)}–{timeOf(current.end)}</span>
                  <strong>{current.title}</strong>
                  {current.description && <p className="muted">{current.description}</p>}
                  <div className="bar"><span style={{ width: `${pct}%` }} /></div>
                </li>
              )}
              {upcoming.map((e, i) => (
                <li key={`${e.start}-${i}`}><span className="time">{timeOf(e.start)}</span>{e.title}</li>
              ))}
            </ul>
          ) : <p className="muted">{tr("No programme guide for this channel.")}</p>}
        </>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ movies and series

function GridTab({ source, kind }: { source: string; kind: "vod" | "series" }) {
  const [params, setParams] = useSearchParams();
  const category = params.get("c") ?? "";
  const sort = params.get("sort") ?? "added";
  const [query, setQuery] = useState("");
  const [cats, setCats] = useState<IptvCategory[] | null>(null);
  const [page, setPage] = useState<{ total: number; items: IptvItem[] } | null>(null);
  const [error, setError] = useState("");
  const set = (k: string, v: string) => { if (v) params.set(k, v); else params.delete(k); setParams(params, { replace: true }); };

  useEffect(() => { iptvApi.categories(source, kind).then(setCats).catch(() => setCats([])); }, [source, kind]);
  useEffect(() => {
    let alive = true;
    setPage(null);
    const t = window.setTimeout(() => {
      iptvApi.items(source, { kind, category: category || undefined, q: query || undefined, sort, limit: 120 })
        .then((p) => { if (alive) { setPage(p); setError(""); } })
        .catch((e) => { if (alive) { setPage({ total: 0, items: [] }); setError(errorText(e, tr("Can't load this list."))); } });
    }, query ? 250 : 0);
    return () => { alive = false; window.clearTimeout(t); };
  }, [source, kind, category, query, sort]);

  const more = () => {
    if (!page) return;
    iptvApi.items(source, { kind, category: category || undefined, q: query || undefined, sort, offset: page.items.length, limit: 120 })
      .then((p) => setPage({ total: p.total, items: [...page.items, ...p.items] })).catch(() => undefined);
  };
  const to = (i: IptvItem) => (kind === "vod" ? `/tv/${source}/movie/${i.id}` : `/tv/${source}/show/${i.id}`);

  return (
    <div className="tv-grid-wrap">
      <Categories cats={cats} value={category} onChange={(c) => set("c", c)} allCount={cats?.reduce((n, c) => n + c.count, 0)} />
      <div>
        <div className="tv-tools">
          <label className="search">
            <Search size={17} aria-hidden />
            <input placeholder={kind === "vod" ? tr("Search movies") : tr("Search series")} value={query}
              onChange={(e) => setQuery(e.target.value)} aria-label={kind === "vod" ? tr("Search movies") : tr("Search series")} />
          </label>
          <select value={sort} onChange={(e) => set("sort", e.target.value)} aria-label={tr("Sort")}>
            <option value="added">{tr("Newest first")}</option>
            <option value="name">{tr("A to Z")}</option>
            <option value="rating">{tr("Top rated")}</option>
            <option value="default">{tr("Provider's order")}</option>
          </select>
        </div>
        {error && <p className="error" role="alert">{error}</p>}
        {page === null && <p className="muted">{tr("Loading…")}</p>}
        {page && page.items.length === 0 && !error && <p className="muted">{tr("Nothing here.")}</p>}
        <div className="poster-grid">
          {page?.items.map((i) => (
            <Link key={i.id} to={to(i)} className="poster">
              <div className="poster-art">
                {i.icon ? <img src={i.icon} alt="" loading="lazy" onError={(e) => { e.currentTarget.style.display = "none"; }} /> : <span className="poster-blank">{i.name}</span>}
                {i.rating ? <span className="poster-flag">★ {digits(i.rating.toFixed(1))}</span> : null}
              </div>
              <span className="poster-title">{i.name}</span>
              {i.year && <span className="poster-meta">{digits(i.year)}</span>}
            </Link>
          ))}
        </div>
        {page && page.items.length < page.total && <button className="tv-more" onClick={more}>{tr("Show more ({n} left)", { n: page.total - page.items.length })}</button>}
      </div>
    </div>
  );
}

const posKey = (source: string, kind: string, id: string) => `zirahive.tv.pos.${source}.${kind}.${id}`;

/** /tv/:source/movie/:id */
export function TvMoviePage() {
  const { source = "", id = "" } = useParams();
  const [movie, setMovie] = useState<IptvMovie | null>(null);
  const [error, setError] = useState("");
  const fav = useFavorites(source);
  useEffect(() => { iptvApi.movie(source, id).then(setMovie).catch((e) => setError(errorText(e, tr("Can't load this movie.")))); }, [source, id]);
  if (error) return <div className="tv-page"><BackLink source={source} tab="movies" /><p className="error" role="alert">{error}</p></div>;
  if (!movie) return <div className="tv-page" aria-busy="true" />;
  const pos = load<number>(posKey(source, "vod", id), 0);
  const play = `/tv/${source}/play/vod/${id}?ext=${movie.ext}&title=${encodeURIComponent(movie.name)}` +
    (movie.duration ? `&d=${movie.duration}` : "") + (movie.height ? `&h=${movie.height}` : "");
  return (
    <div className="tv-page">
      <BackLink source={source} tab="movies" />
      <Detail title={movie.name} poster={movie.poster} backdrop={movie.backdrop}
        meta={[movie.year, movie.duration ? formatDuration(movie.duration) : null, movie.genre, movie.rating ? `★ ${movie.rating.toFixed(1)}` : null]}>
        <div className="tv-actions">
          <Link to={play} className="button primary"><Play size={17} aria-hidden />{" "}{pos > 30 ? tr("Resume") : tr("Play")}</Link>
          {pos > 30 && <Link to={`${play}&from=0`} className="button">{tr("From the start")}</Link>}
          <StarButton on={fav.isFav("vod", id)} onClick={() => void fav.toggle("vod", { id, name: movie.name, icon: movie.poster, ext: movie.ext })} />
        </div>
        {movie.plot && <p>{movie.plot}</p>}
        {movie.director && <p className="muted">{tr("Director")}: {movie.director}</p>}
        {movie.cast && <p className="muted">{tr("Cast")}: {movie.cast}</p>}
      </Detail>
    </div>
  );
}

/** /tv/:source/show/:id */
export function TvSeriesPage() {
  const { source = "", id = "" } = useParams();
  const [series, setSeries] = useState<IptvSeries | null>(null);
  const [error, setError] = useState("");
  const [season, setSeason] = useState<number | null>(null);
  const fav = useFavorites(source);
  useEffect(() => { iptvApi.series(source, id).then(setSeries).catch((e) => setError(errorText(e, tr("Can't load this series.")))); }, [source, id]);
  const seasons = useMemo(() => [...new Set(series?.episodes.map((e) => e.season) ?? [])], [series]);
  const lastEp = load<string | null>(`zirahive.tv.lastep.${source}.${id}`, null);
  useEffect(() => {
    if (!series || season !== null) return;
    const resume = series.episodes.find((e) => e.id === lastEp);
    setSeason(resume?.season ?? seasons[0] ?? 1);
  }, [series, seasons, season, lastEp]);
  if (error) return <div className="tv-page"><BackLink source={source} tab="series" /><p className="error" role="alert">{error}</p></div>;
  if (!series) return <div className="tv-page" aria-busy="true" />;
  const play = (e: IptvEpisode) => `/tv/${source}/play/episode/${e.id}?ext=${e.ext}&series=${id}` +
    `&title=${encodeURIComponent(`${series.name} · ${e.title}`)}` + (e.duration ? `&d=${e.duration}` : "") + (e.height ? `&h=${e.height}` : "");
  return (
    <div className="tv-page">
      <BackLink source={source} tab="series" />
      <Detail title={series.name} poster={series.poster} backdrop={series.backdrop}
        meta={[series.year, series.genre, series.rating ? `★ ${series.rating.toFixed(1)}` : null,
          tr("{n} episodes", { n: series.episodes.length })]}>
        <div className="tv-actions">
          <StarButton on={fav.isFav("series", id)} onClick={() => void fav.toggle("series", { id, name: series.name, icon: series.poster })} />
        </div>
        {series.plot && <p>{series.plot}</p>}
        {series.cast && <p className="muted">{tr("Cast")}: {series.cast}</p>}
      </Detail>
      {seasons.length > 1 && (
        <nav className="lib-tabs tv-seasons" aria-label={tr("Seasons")}>
          {seasons.map((s) => <button key={s} className={season === s ? "active" : ""} onClick={() => setSeason(s)}>{tr("Season {n}", { n: s })}</button>)}
        </nav>
      )}
      <ol className="tv-episodes">
        {series.episodes.filter((e) => e.season === season).map((e) => {
          const pos = load<number>(posKey(source, "episode", e.id), 0);
          const pct = e.duration && pos ? Math.min(100, (pos / e.duration) * 100) : 0;
          return (
            <li key={e.id} className={e.id === lastEp ? "last" : ""}>
              <Link to={play(e)}>
                <span className="tv-ep-art">
                  {e.image ? <img src={e.image} alt="" loading="lazy" onError={(ev) => { ev.currentTarget.style.display = "none"; }} /> : <Play size={20} aria-hidden />}
                  {pct > 0 && <span className="poster-progress"><span style={{ width: `${pct}%` }} /></span>}
                </span>
                <span className="tv-ep-text">
                  <strong>{e.episode != null ? `${digits(String(e.episode))}. ` : ""}{e.title}</strong>
                  {e.duration ? <span className="muted"> · {formatDuration(e.duration)}</span> : null}
                  {e.plot && <span className="muted tv-ep-plot">{e.plot}</span>}
                </span>
              </Link>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function BackLink({ source, tab }: { source: string; tab: string }) {
  return <Link to={`/tv/${source}/${tab}`} className="tv-back"><ChevronLeft size={18} aria-hidden />{" "}{tab === "movies" ? tr("Movies") : tr("Series")}</Link>;
}

function Detail({ title, poster, backdrop, meta, children }: {
  title: string; poster: string | null; backdrop: string | null; meta: (string | null | undefined)[]; children: ReactNode;
}) {
  return (
    <div className="tv-detail" style={backdrop ? ({ "--tv-backdrop": `url("${backdrop}")` } as CSSProperties) : undefined}>
      <div className="tv-cover">{poster ? <img src={poster} alt="" /> : <span className="poster-blank">{title}</span>}</div>
      <div className="tv-info">
        <h1>{title}</h1>
        <p className="muted">{digits(meta.filter(Boolean).join(" · "))}</p>
        {children}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ the film / episode player

/** /tv/:source/play/:kind/:id?ext=&d=&h=&title=&series= */
export function TvPlayerPage() {
  const { source = "", kind = "vod", id = "" } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const title = params.get("title") ?? "";
  const seriesId = params.get("series");
  const [info, setInfo] = useState<IptvPlay | null>(null);
  const [choice, setChoice] = useState<string | null>(null);  // "direct", "convert" or a quality
  const [error, setError] = useState("");
  const video = useRef<HTMLVideoElement>(null);
  const frame = useRef<HTMLDivElement>(null);
  const key = posKey(source, kind, id);
  const startAt = useRef<number>(params.get("from") === "0" ? 0 : load<number>(key, 0));

  useEffect(() => {
    if (seriesId) save(`zirahive.tv.lastep.${source}.${seriesId}`, id);
    const num = (k: string) => { const v = Number(params.get(k)); return Number.isFinite(v) && v > 0 ? v : undefined; };
    iptvApi.play(source, kind as IptvStreamKind, id, { ext: params.get("ext") ?? undefined, duration: num("d"), height: num("h") })
      .then((p) => {
        setInfo(p);
        const q = p.qualities ?? [];
        setChoice(p.mode === "direct" ? "direct" : p.mode === "hls" ? (q.includes("720p") ? "720p" : q[0]) : "convert");
      })
      .catch((e) => setError(errorText(e, tr("This video couldn't be played."))));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source, kind, id]);

  useEffect(() => {
    if (!nativeApp || !info || !choice) return;
    const hls = info.hls_url && info.qualities?.length ? info.hls_url.replace("{quality}", info.qualities.includes("720p") ? "720p" : info.qualities[0]) : null;
    const url = choice === "direct" && info.direct_url ? info.direct_url
      : choice === "convert" ? withViewer(info.convert_url) : (info.hls_url ?? "").replace("{quality}", choice);
    const fallback = url === info.direct_url ? (hls ?? withViewer(info.convert_url)) : undefined;
    nativeApp.play({ url, fallbackUrl: fallback, title, start: choice === "convert" ? 0 : startAt.current, key });
  }, [info, choice]);  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => onPlayerClosed((r) => {
    if (r.key !== key) return;
    if (r.finished || (r.duration && r.position > r.duration * 0.95)) { try { localStorage.removeItem(key); } catch { /* ignore */ } }
    else if (r.position > 5) save(key, Math.floor(r.position));
    stopWatching();
    navigate(-1);
  }), [key, navigate]);

  useEffect(() => {
    const v = video.current;
    if (!v || !info || !choice || nativeApp) return;
    setError("");
    const at = v.currentTime > 1 ? v.currentTime : startAt.current;
    const fallback = () => {
      const q = info.qualities ?? [];
      if (choice === "direct" && q.length) setChoice(q.includes("720p") ? "720p" : q[0]);
      else if (choice !== "convert" && !q.length) setChoice("convert");
      else setError(tr("This video couldn't be played."));
    };
    if (choice === "direct" && info.direct_url) {
      const onError = () => fallback();
      v.addEventListener("error", onError);
      v.src = info.direct_url;
      v.addEventListener("loadedmetadata", () => { if (at > 0) v.currentTime = at; }, { once: true });
      void v.play().catch(() => undefined);
      return () => { v.removeEventListener("error", onError); v.removeAttribute("src"); v.load(); };
    }
    const src = choice === "convert" ? withViewer(info.convert_url) : (info.hls_url ?? "").replace("{quality}", choice);
    return playHls(v, src, {
      startAt: choice === "convert" ? undefined : at,
      onFatal: (_codec, msg) => { if (msg) setError(msg); else fallback(); },
    });
  }, [info, choice]);

  // remember where we got to
  useEffect(() => {
    const v = video.current;
    if (!v) return;
    const remember = () => {
      if (!v.duration || !Number.isFinite(v.duration) || v.currentTime < 5) return;
      if (v.currentTime > v.duration * 0.95) { try { localStorage.removeItem(key); } catch { /* ignore */ } return; }
      save(key, Math.floor(v.currentTime));
    };
    const timer = window.setInterval(remember, 10000);
    v.addEventListener("pause", remember);
    return () => { remember(); window.clearInterval(timer); v.removeEventListener("pause", remember); stopWatching(); };
  }, [key]);

  const options = [...(info?.direct_url ? ["direct"] : []), ...(info?.qualities ?? []), ...(info && !info.qualities?.length ? ["convert"] : [])];
  return (
    <div className="player-page tv-vod">
      <button className="tv-back" onClick={() => navigate(-1)}><ChevronLeft size={18} aria-hidden />{" "}{tr("Back")}</button>
      <div className="player-frame" ref={frame}>
        <video ref={video} controls playsInline autoPlay onDoubleClick={() => fullscreen(frame.current)} />
        {!info && !error && <div className="tv-overlay">{tr("Loading…")}</div>}
        {info && !error && nativeApp && <div className="tv-overlay">{tr("Playing in the ZiraHive player.")}</div>}
        {error && <div className="tv-overlay error" role="alert"><p>{error}</p></div>}
      </div>
      <div className="player-controls">
        <h1 className="tv-vod-title">{title}</h1>
        {options.length > 1 && (
          <label>{tr("Quality")}
            <select value={choice ?? ""} onChange={(e) => setChoice(e.target.value)}>
              {options.map((o) => <option key={o} value={o}>{o === "direct" ? tr("Original") : o === "convert" ? tr("Converted") : o}</option>)}
            </select>
          </label>
        )}
        {info?.mode === "convert" && <p className="muted">{tr("This video is converted while you watch, so you can only skip back, not ahead.")}</p>}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ favourites

function FavoritesTab({ source }: { source: string }) {
  const { favs, toggle } = useFavorites(source);
  const groups: { kind: IptvKind; label: string }[] = [{ kind: "live", label: "Channels" }, { kind: "vod", label: "Movies" }, { kind: "series", label: "Series" }];
  if (!favs.length) return <div className="empty"><h2>{tr("No favourites yet")}</h2><p>{tr("Tap the star on a channel, movie or series to keep it here.")}</p></div>;
  const to = (f: IptvFavorite) => f.kind === "live"
    ? `/tv/${source}/live?ch=${encodeURIComponent(f.stream_id)}&n=${encodeURIComponent(f.name)}${f.icon ? `&i=${encodeURIComponent(f.icon)}` : ""}`
    : f.kind === "vod" ? `/tv/${source}/movie/${f.stream_id}` : `/tv/${source}/show/${f.stream_id}`;
  return (
    <>
      {groups.map(({ kind, label }) => {
        const list = favs.filter((f) => f.kind === kind);
        if (!list.length) return null;
        return (
          <section key={kind} className="shelf-block">
            <h2 className="shelf-title">{tr(label)}</h2>
            <div className={kind === "live" ? "tv-fav-channels" : "poster-grid"}>
              {list.map((f) => kind === "live" ? (
                <div key={f.id} className="tv-fav-ch">
                  <Link to={to(f)}><Logo src={f.icon} name={f.name} className="ch-logo big" /><span>{f.name}</span></Link>
                  <StarButton on onClick={() => void toggle(kind, { id: f.stream_id, name: f.name, icon: f.icon })} />
                </div>
              ) : (
                <Link key={f.id} to={to(f)} className="poster">
                  <div className="poster-art">{f.icon ? <img src={f.icon} alt="" loading="lazy" /> : <span className="poster-blank">{f.name}</span>}</div>
                  <span className="poster-title">{f.name}</span>
                </Link>
              ))}
            </div>
          </section>
        );
      })}
    </>
  );
}

// ------------------------------------------------------------------ sources (subscriptions)

/** /tv/sources */
export function TvSourcesPage() {
  const { sources, reload } = useSources();
  const [editing, setEditing] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [accounts, setAccounts] = useState<Record<string, IptvAccount | string>>({});
  useEffect(() => {
    sources?.filter((s) => s.can_manage).forEach((s) => {
      iptvApi.account(s.id).then((a) => setAccounts((x) => ({ ...x, [s.id]: a })))
        .catch((e) => setAccounts((x) => ({ ...x, [s.id]: errorText(e, tr("Can't reach the IPTV server.")) })));
    });
  }, [sources]);
  const remove = async (s: IptvSource) => {
    if (!confirm(tr("Remove {name}? Favourites from it are removed too.", { name: s.name }))) return;
    await iptvApi.deleteSource(s.id).catch(() => undefined);
    reload();
  };
  return (
    <div className="tv-page tv-sources">
      <div className="page-head">
        <h1>{tr("IPTV sources")}</h1>
        {sources?.length ? <Link to="/tv" className="button">{tr("Back to Live TV")}</Link> : null}
        <button className="primary" onClick={() => setAdding(true)}><Plus size={16} aria-hidden />{" "}{tr("Add")}</button>
      </div>
      {adding && <SourceForm onDone={() => { setAdding(false); reload(); }} onCancel={() => setAdding(false)} />}
      <ul className="rows">
        {sources?.map((s) => {
          const acc = accounts[s.id];
          return (
            <li key={s.id} className="tv-source-row">
              {editing === s.id ? (
                <SourceForm source={s} onDone={() => { setEditing(null); reload(); }} onCancel={() => setEditing(null)} />
              ) : (
                <>
                  <div>
                    <strong>{s.name}</strong>{s.shared && <span className="tv-tag">{tr("Shared with everyone")}</span>}
                    {s.server && <div className="muted">{s.server} · {s.username}</div>}
                    {typeof acc === "string" && <div className="error">{acc}</div>}
                    {acc && typeof acc !== "string" && (
                      <div className="muted">
                        {tx(acc.status)}
                        {acc.expires_at && <> · {tr("Expires {date}", { date: new Date(acc.expires_at).toLocaleDateString(locale()) })}</>}
                        {acc.max_connections != null && <> · {tr("{n} screens at once", { n: acc.max_connections })}</>}
                        {acc.is_trial && <> · {tr("Trial")}</>}
                      </div>
                    )}
                  </div>
                  <Link to={`/tv/${s.id}/live`} className="button">{tr("Watch")}</Link>
                  {s.can_manage && <button className="icon" onClick={() => setEditing(s.id)} aria-label={tr("Edit")} title={tr("Edit")}><Pencil size={17} /></button>}
                  {s.can_manage && <button className="icon danger" onClick={() => void remove(s)} aria-label={tr("Remove")} title={tr("Remove")}><Trash2 size={17} /></button>}
                </>
              )}
            </li>
          );
        })}
      </ul>
      {sources && !sources.length && !adding && <SourceForm onDone={reload} />}
    </div>
  );
}

function SourceForm({ source, onDone, onCancel }: { source?: IptvSource; onDone?: () => void; onCancel?: () => void }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [name, setName] = useState(source?.name ?? tr("My IPTV"));
  const [server, setServer] = useState(source?.server ?? "");
  const [port, setPort] = useState("");
  const [username, setUsername] = useState(source?.username ?? "");
  const [password, setPassword] = useState("");
  const [shared, setShared] = useState(source?.shared ?? false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (source) {
        await iptvApi.updateSource(source.id, {
          name, ...(server !== (source.server ?? "") || port ? { server } : {}), ...(port ? { port } : {}),
          ...(username !== (source.username ?? "") ? { username } : {}),
          ...(password ? { password } : {}), ...(user.is_admin ? { shared } : {}),
        });
        onDone?.();
      } else {
        const created = await iptvApi.addSource({ name, server, port: port || undefined, username, password, shared: user.is_admin && shared });
        onDone?.();
        navigate(`/tv/${created.id}/live`);
      }
    } catch (err) {
      setError(errorText(err, tr("Can't reach the server.")));
    } finally { setBusy(false); }
  };

  return (
    <form className="tv-form" onSubmit={submit}>
      <label>{tr("Name")}<input value={name} onChange={(e) => setName(e.target.value)} required maxLength={80} /></label>
      <div className="tv-form-row">
        <label className="grow">{tr("Server address")}
          <input value={server} onChange={(e) => setServer(e.target.value)} placeholder="http://example.com" required={!source}
            inputMode="url" autoComplete="off" spellCheck={false} />
        </label>
        <label className="port">{tr("Port")}
          <input value={port} onChange={(e) => setPort(e.target.value.replace(/\D/g, ""))} placeholder="8080" inputMode="numeric" maxLength={5} />
        </label>
      </div>
      <label>{tr("Username")}<input value={username} onChange={(e) => setUsername(e.target.value)} required={!source} autoComplete="off" spellCheck={false} /></label>
      <label>{tr("Password")}
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required={!source} autoComplete="new-password"
          placeholder={source ? tr("Leave empty to keep the current one") : undefined} />
      </label>
      {user.is_admin && (
        <label className="check"><input type="checkbox" checked={shared} onChange={(e) => setShared(e.target.checked)} />{" "}
          {tr("Let everyone in the family watch it (they won't see the login)")}</label>
      )}
      <p className="muted tv-note">{tr("ZiraHive checks the login with your provider before saving. The password stays on your ZiraHive server.")}</p>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="tv-actions">
        <button className="primary" disabled={busy}>{busy ? tr("Checking…") : source ? tr("Save") : tr("Add and start watching")}</button>
        {onCancel && <button type="button" onClick={onCancel}>{tr("Cancel")}</button>}
      </div>
    </form>
  );
}
