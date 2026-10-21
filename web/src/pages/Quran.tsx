// Quran & Namaz: recitations by qari (files in a "Quran" category, or added here), and the prayer
// times for where you are, with a countdown, a tracker and the Qibla direction.
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, NavLink, useParams, useSearchParams } from "react-router-dom";
import { BookOpen, Compass, MapPin, Pause, Play, Plus, Search, Settings2, Shuffle, Upload } from "lucide-react";
import { api, ApiError, url, type PrayerLogEntry, type PrayerStatus, type QuranHome, type ReciterDetail, type Surah, type Track } from "../api";
import { useAuth } from "../App";
import { clock, useAudio } from "../audio";
import Dialog from "../components/Dialog";
import { digits, lang, locale, t as tr } from "../i18n";
import {
  addDays, dateIn, dayKey, distanceToMakkah, FARD, hijri, METHODS, methodFor, momentAt, PLACES, PRAYERS, qibla,
  type Method, type PrayerName, type PrayerSettings,
} from "../prayer";
import { TrackList } from "./Listen";
import { nativeApp } from "../native";

// ------------------------------------------------------------------ shared

export function prayerLabel(p: PrayerName | string): string {
  switch (p) {
    case "fajr": return tr("Fajr");
    case "sunrise": return tr("Sunrise");
    case "dhuhr": return tr("Dhuhr");
    case "jumuah": return tr("Jumu'ah");
    case "asr": return tr("Asr");
    case "maghrib": return tr("Maghrib");
    case "isha": return tr("Isha");
    default: return p;
  }
}

function QuranTabs() {
  return (
    <nav className="lib-tabs" aria-label={tr("Quran & Namaz")}>
      <NavLink to="/quran" end>{tr("Qaris")}</NavLink>
      <NavLink to="/quran/surahs">{tr("Surahs")}</NavLink>
      <NavLink to="/quran/namaz">{tr("Namaz")}</NavLink>
    </nav>
  );
}

function Page({ title, children, actions }: { title: string; children: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="page cinema-page quran-page">
      <header className="page-head"><h1>{title}</h1>{actions && <div className="head-actions">{actions}</div>}</header>
      <QuranTabs />
      {children}
    </div>
  );
}

let surahCache: Promise<Surah[]> | null = null;
function useSurahs(): Surah[] {
  const [list, setList] = useState<Surah[]>([]);
  useEffect(() => {
    surahCache ??= api.surahs().catch((e) => { surahCache = null; throw e; });
    surahCache.then(setList).catch(() => undefined);
  }, []);
  return list;
}

function surahName(s: Surah | undefined, n: number): string {
  if (!s) return tr("Surah {n}", { n });
  return lang() === "bn" ? s.bangla : s.name;
}

function hours(sec: number): string {
  if (!sec) return "";
  const h = Math.floor(sec / 3600), m = Math.round((sec % 3600) / 60);
  return h ? tr("{h} h {m} min", { h, m }) : tr("{m} min", { m });
}

const withLink = (tracks: Track[], link: string) => tracks.map((t) => ({ ...t, link }));
const qariLink = (name: string) => `/quran/qari?name=${encodeURIComponent(name)}`;

// ------------------------------------------------------------- prayer settings, shared by the pages

const SETTINGS_EVENT = "zirahive:prayer-settings";
let settingsCache: Promise<PrayerSettings> | null = null;

export function loadPrayerSettings(fresh = false): Promise<PrayerSettings> {
  if (fresh || !settingsCache) settingsCache = api.prayerSettings().catch((e) => { settingsCache = null; throw e; });
  return settingsCache;
}

function usePrayerSettings(): [PrayerSettings | null, (s: PrayerSettings) => Promise<void>] {
  const [s, setS] = useState<PrayerSettings | null>(null);
  useEffect(() => {
    loadPrayerSettings().then(setS).catch(() => undefined);
    const on = () => loadPrayerSettings().then(setS).catch(() => undefined);
    window.addEventListener(SETTINGS_EVENT, on);
    return () => window.removeEventListener(SETTINGS_EVENT, on);
  }, []);
  const save = async (next: PrayerSettings) => {
    const saved = await api.savePrayerSettings(next);
    settingsCache = Promise.resolve(saved);
    setS(saved);
    nativeApp?.prayerSettingsChanged();
    window.dispatchEvent(new Event(SETTINGS_EVENT));
  };
  return [s, save];
}

/** Ticks every `ms` so countdowns move. */
function useNow(ms = 1000): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => { const id = window.setInterval(() => setNow(new Date()), ms); return () => window.clearInterval(id); }, [ms]);
  return now;
}

function timeText(d: Date, tz: string | null): string {
  return new Intl.DateTimeFormat(locale() ?? "en", { hour: "numeric", minute: "2-digit", timeZone: tz ?? undefined }).format(d);
}

function countdown(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return digits(h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`);
}

// -------------------------------------------------------------------- Qaris (home)

export function QuranHomePage() {
  const { user } = useAuth();
  const [home, setHome] = useState<QuranHome | null>(null);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");
  const load = () => api.quranHome().then(setHome).catch((e) => setError((e as Error).message));
  useEffect(() => { void load(); }, []);
  return (
    <Page title={tr("Quran & Namaz")}
      actions={user.is_admin && <button onClick={() => setAdding(true)}><Upload size={16} />{" "}{tr("Add recitations")}</button>}>
      <NextPrayerCard />
      {error && <p className="error" role="alert">{error}</p>}
      {home && home.recent.length > 0 && (
        <section className="shelf-block">
          <h2 className="shelf-title">{tr("Continue listening")}</h2>
          <TrackList tracks={withLink(home.recent.slice(0, 6), "/quran")} showAlbum={false} />
        </section>
      )}
      {home && home.reciters.length > 0 && (
        <section className="shelf-block">
          <h2 className="shelf-title">{tr("Qaris")}</h2>
          <div className="mtile-grid">
            {home.reciters.map((r) => (
              <Link key={r.name} to={qariLink(r.name)} className="mtile">
                <div className="cover round qari-cover">
                  {r.cover_album_id ? <img src={url.albumCover({ id: r.cover_album_id })} alt="" loading="lazy" />
                    : <span className="cover-blank" aria-hidden>{r.name.slice(0, 1).toUpperCase()}</span>}
                </div>
                <span className="poster-title">{r.name}</span>
                <span className="poster-meta">{tr("{n} of 114 surahs", { n: r.surahs })}{r.duration ? ` · ${hours(r.duration)}` : ""}</span>
              </Link>
            ))}
          </div>
        </section>
      )}
      {home && home.reciters.length === 0 && (
        <section className="panel empty-quran">
          <BookOpen size={28} aria-hidden />
          <h2>{tr("No recitations yet")}</h2>
          <p className="muted">{tr("Put a folder named Quran in your media folder with a folder for each qari inside (Quran/Mishary Alafasy/001.mp3, 002.mp3…), or add the files here. Files can be named by number (001.mp3, 002255.mp3 for single ayahs) or by surah name (Surah Yasin.mp3).")}</p>
          {user.is_admin && <button className="primary" onClick={() => setAdding(true)}><Upload size={16} />{" "}{tr("Add recitations")}</button>}
        </section>
      )}
      {adding && <AddRecitations known={home?.reciters.map((r) => r.name) ?? []} onClose={() => setAdding(false)} onDone={() => void load()} />}
    </Page>
  );
}

function AddRecitations({ known, onClose, onDone, qari = "" }: { known: string[]; onClose: () => void; onDone: () => void; qari?: string }) {
  const [name, setName] = useState(qari);
  const [files, setFiles] = useState<File[]>([]);
  const [done, setDone] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const total = files.reduce((n, f) => n + f.size, 0);
  const send = async () => {
    setBusy(true); setError(""); setDone(0);
    try {
      for (let i = 0; i < files.length; i++) {
        await api.addRecitation(name.trim(), files[i]);
        setDone(i + 1);
      }
      await api.rescanQuran();
      onDone();
      // the scan runs in the background; look again in a moment so the new files show up
      window.setTimeout(onDone, 4000);
      onClose();
    } catch (e) {
      setError((e as ApiError).message);
    } finally { setBusy(false); }
  };
  return (
    <Dialog title={tr("Add recitations")} onClose={busy ? () => undefined : onClose}>
      <form className="stack-form" onSubmit={(e) => { e.preventDefault(); if (name.trim() && files.length) void send(); }}>
        <label>{tr("Qari")}
          <input value={name} onChange={(e) => setName(e.target.value)} list="qari-names" required maxLength={120}
            placeholder={tr("e.g. Mishary Rashid Alafasy")} />
          <datalist id="qari-names">{known.map((k) => <option key={k} value={k} />)}</datalist>
        </label>
        <input ref={input} type="file" accept="audio/*,.mp3,.m4a,.ogg,.opus,.flac,.wav" multiple hidden
          onChange={(e) => setFiles(Array.from(e.target.files ?? []))} />
        <button type="button" onClick={() => input.current?.click()} disabled={busy}><Plus size={16} />{" "}{tr("Choose audio files")}</button>
        {files.length > 0 && (
          <p className="muted small">{tr("{n} files, {size}", { n: files.length, size: `${(total / 1048576).toFixed(1)} MB` })}</p>
        )}
        <p className="muted small">{tr("Name files by surah number (001.mp3 … 114.mp3) or surah name; ZiraHive puts them in order.")}</p>
        {busy && <progress max={files.length} value={done} aria-label={tr("Uploading…")} />}
        {error && <p className="error" role="alert">{error}</p>}
        <div className="admin-row">
          <button className="primary" disabled={busy || !name.trim() || !files.length}>
            {busy ? tr("Uploading {done} of {n}…", { done, n: files.length }) : tr("Add")}
          </button>
          <button type="button" onClick={onClose} disabled={busy}>{tr("Cancel")}</button>
        </div>
      </form>
    </Dialog>
  );
}

// -------------------------------------------------------------------- one qari

export function QariPage() {
  const [params] = useSearchParams();
  const name = params.get("name") ?? "";
  const { user } = useAuth();
  const a = useAudio();
  const surahs = useSurahs();
  const [r, setR] = useState<ReciterDetail | null>(null);
  const [error, setError] = useState("");
  const [adding, setAdding] = useState(false);
  const load = () => api.reciter(name).then(setR).catch((e) => setError((e as Error).message));
  useEffect(() => { void load(); }, [name]);  // eslint-disable-line react-hooks/exhaustive-deps
  const link = qariLink(name);
  const all = useMemo(() => (r ? withLink(r.surahs.flatMap((s) => s.tracks), link) : []), [r, link]);
  const firstIndex = useMemo(() => {
    const m = new Map<number, number>();
    let i = 0;
    for (const s of r?.surahs ?? []) { m.set(s.number, i); i += s.tracks.length; }
    return m;
  }, [r]);
  const playingSurah = (n: number) => {
    const s = r?.surahs.find((x) => x.number === n);
    return !!s && a.current?.kind === "track" && s.tracks.some((t) => t.id === a.current!.id);
  };
  return (
    <div className="page cinema-page quran-page">
      <Link to="/quran" className="back">{tr("Quran & Namaz")}</Link>
      <header className="page-head">
        <h1>{name}</h1>
        {user.is_admin && <div className="head-actions"><button onClick={() => setAdding(true)}><Upload size={16} />{" "}{tr("Add files")}</button></div>}
      </header>
      {error && <p className="error" role="alert">{error}</p>}
      {r && (
        <>
          <p className="muted">{tr("{n} of 114 surahs", { n: r.surahs.length })}{all.length ? ` · ${hours(r.surahs.reduce((x, s) => x + s.duration, 0))}` : ""}</p>
          <div className="admin-row">
            <button className="primary" onClick={() => a.playTracks(all)} disabled={!all.length}><Play size={17} fill="currentColor" />{" "}{tr("Play in order")}</button>
            <button onClick={() => a.playTracks(all, 0, true)} disabled={!all.length}><Shuffle size={17} />{" "}{tr("Shuffle")}</button>
          </div>
          <ol className="surah-list">
            {r.surahs.map((s) => {
              const info = surahs.find((x) => x.number === s.number);
              const now = playingSurah(s.number);
              return (
                <li key={s.number} className={now ? "now" : ""}>
                  <button className="surah-row" onClick={() => (now ? a.toggle() : a.playTracks(all, firstIndex.get(s.number) ?? 0))}
                    aria-label={now && a.playing ? tr("Pause {title}", { title: surahName(info, s.number) }) : tr("Play {title}", { title: surahName(info, s.number) })}>
                    <span className="surah-no">{now ? (a.playing ? <Pause size={15} /> : <Play size={15} />) : digits(String(s.number))}</span>
                    <span className="surah-text">
                      <span className="surah-name">{surahName(info, s.number)}</span>
                      <span className="muted small">
                        {info ? [tr("{n} ayahs", { n: info.ayahs }), info.place === "makkah" ? tr("Makki") : tr("Madani")].join(" · ") : ""}
                        {s.tracks.length > 1 ? ` · ${tr("{n} files", { n: s.tracks.length })}` : ""}
                      </span>
                    </span>
                    {info && <span className="surah-ar" lang="ar" dir="rtl">{info.arabic}</span>}
                    <span className="muted small track-dur">{clock(s.duration)}</span>
                  </button>
                </li>
              );
            })}
          </ol>
          {r.other.length > 0 && (
            <section className="shelf-block">
              <h2 className="shelf-title">{tr("Duas and more")}</h2>
              <TrackList tracks={withLink(r.other, link)} showAlbum={false} />
            </section>
          )}
        </>
      )}
      {adding && <AddRecitations known={[name]} qari={name} onClose={() => setAdding(false)} onDone={() => void load()} />}
    </div>
  );
}

// -------------------------------------------------------------------- surahs

export function SurahsPage() {
  const surahs = useSurahs();
  const [q, setQ] = useState("");
  const shown = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return surahs;
    const n = Number(s.replace(/[০-৯]/g, (d) => String("০১২৩৪৫৬৭৮৯".indexOf(d))));
    return surahs.filter((x) => x.number === n || x.name.toLowerCase().includes(s) || x.bangla.includes(q.trim()) || x.arabic.includes(q.trim()));
  }, [q, surahs]);
  return (
    <Page title={tr("Quran & Namaz")}>
      <label className="search quran-search">
        <Search size={16} aria-hidden />
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder={tr("Find a surah by name or number")} aria-label={tr("Find a surah")} />
      </label>
      <ol className="surah-list">
        {shown.map((s) => (
          <li key={s.number}>
            <Link className="surah-row" to={`/quran/surah/${s.number}`}>
              <span className="surah-no">{digits(String(s.number))}</span>
              <span className="surah-text">
                <span className="surah-name">{surahName(s, s.number)}</span>
                <span className="muted small">{[tr("{n} ayahs", { n: s.ayahs }), s.place === "makkah" ? tr("Makki") : tr("Madani")].join(" · ")}</span>
              </span>
              <span className="surah-ar" lang="ar" dir="rtl">{s.arabic}</span>
            </Link>
          </li>
        ))}
      </ol>
    </Page>
  );
}

export function SurahPage() {
  const n = Number(useParams().n);
  const surahs = useSurahs();
  const a = useAudio();
  const info = surahs.find((s) => s.number === n);
  const [list, setList] = useState<{ reciter: string; tracks: Track[]; duration: number }[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.surahReciters(n).then(setList).catch((e) => setError((e as Error).message)); }, [n]);
  return (
    <div className="page cinema-page quran-page">
      <Link to="/quran/surahs" className="back">{tr("Surahs")}</Link>
      <header className="page-head surah-head">
        <h1>{digits(String(n))}. {surahName(info, n)}</h1>
        {info && <span className="surah-ar big" lang="ar" dir="rtl">{info.arabic}</span>}
      </header>
      {info && <p className="muted">{[info.name, tr("{n} ayahs", { n: info.ayahs }), info.place === "makkah" ? tr("Revealed in Makkah") : tr("Revealed in Madinah")].join(" · ")}</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {list && list.length === 0 && <p className="muted">{tr("None of the qaris here has this surah yet.")}</p>}
      {list && list.length > 0 && (
        <ol className="surah-list">
          {list.map((r) => {
            const tracks = withLink(r.tracks, `/quran/surah/${n}`);
            const now = a.current?.kind === "track" && r.tracks.some((t) => t.id === a.current!.id);
            return (
              <li key={r.reciter} className={now ? "now" : ""}>
                <button className="surah-row" onClick={() => (now ? a.toggle() : a.playTracks(tracks))}
                  aria-label={now && a.playing ? tr("Pause {title}", { title: r.reciter }) : tr("Play {title}", { title: r.reciter })}>
                  <span className="surah-no">{now && a.playing ? <Pause size={15} /> : <Play size={15} />}</span>
                  <span className="surah-text"><span className="surah-name">{r.reciter}</span></span>
                  <span className="muted small track-dur">{clock(r.duration)}</span>
                </button>
                <Link className="link-btn small" to={qariLink(r.reciter)}>{tr("All surahs")}</Link>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}

// -------------------------------------------------------------------- namaz

/** The small "next prayer" card on the Qaris page. */
function NextPrayerCard() {
  const [s] = usePrayerSettings();
  const now = useNow(1000);
  if (!s || s.lat == null) {
    return (
      <Link to="/quran/namaz" className="panel next-prayer small-card">
        <MapPin size={18} aria-hidden /> <span>{tr("Set your place to see prayer times")}</span>
      </Link>
    );
  }
  const m = momentAt(now, s);
  const friday = dateIn(m.nextAt, s.timezone).weekday === 5;
  return (
    <Link to="/quran/namaz" className="panel next-prayer small-card">
      <span className="muted small">{tr("Next")}</span>
      <strong>{m.next === "dhuhr" && friday ? prayerLabel("jumuah") : prayerLabel(m.next)}</strong>
      <span>{timeText(m.nextAt, s.timezone)}</span>
      <span className="np-count">{tr("in {time}", { time: countdown(m.nextAt.getTime() - now.getTime()) })}</span>
    </Link>
  );
}

export function NamazPage() {
  const [s, save] = usePrayerSettings();
  const [editing, setEditing] = useState(false);
  const now = useNow(1000);
  if (!s) return <Page title={tr("Quran & Namaz")}><p className="muted">{tr("Loading…")}</p></Page>;
  const needsPlace = s.lat == null || s.lng == null;
  return (
    <Page title={tr("Quran & Namaz")}
      actions={!needsPlace && <button onClick={() => setEditing(true)}><Settings2 size={16} />{" "}{tr("Place and method")}</button>}>
      {needsPlace ? <PlaceSetup s={s} onSave={save} /> : <NamazToday s={s} now={now} />}
      {!needsPlace && <section className="panel"><BrowserAlertToggle /></section>}
      {editing && (
        <Dialog title={tr("Place and method")} onClose={() => setEditing(false)} wide>
          <PlaceSetup s={s} onSave={async (n) => { await save(n); setEditing(false); }} full />
        </Dialog>
      )}
    </Page>
  );
}

function PlaceSetup({ s, onSave, full = false }: { s: PrayerSettings; onSave: (s: PrayerSettings) => Promise<void>; full?: boolean }) {
  const [draft, setDraft] = useState<PrayerSettings>(s);
  const [find, setFind] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [locating, setLocating] = useState(false);
  const phone = nativeApp?.location ?? null;
  const canLocate = !!phone || (typeof navigator !== "undefined" && "geolocation" in navigator && window.isSecureContext);
  const browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const matches = useMemo(() => {
    const q = find.trim().toLowerCase();
    if (!q) return PLACES.slice(0, 8);
    return PLACES.filter((p) => p.name.toLowerCase().includes(q) || (p.bn ?? "").includes(find.trim())).slice(0, 12);
  }, [find]);
  const set = (change: Partial<PrayerSettings>) => setDraft((d) => ({ ...d, ...change }));
  const locate = () => {
    setLocating(true); setError("");
    if (phone) {
      phone().then(({ lat, lng, timezone }) => {
        setLocating(false);
        const tz = timezone || browserTz;
        set({ lat: Math.round(lat * 10000) / 10000, lng: Math.round(lng * 10000) / 10000, place: tr("My location"), timezone: tz, method: methodFor(tz) });
      }).catch(() => { setLocating(false); setError(tr("Couldn't get your location")); });
      return;
    }
    navigator.geolocation.getCurrentPosition((pos) => {
      setLocating(false);
      const lat = Math.round(pos.coords.latitude * 10000) / 10000, lng = Math.round(pos.coords.longitude * 10000) / 10000;
      set({ lat, lng, place: tr("My location"), timezone: browserTz, method: methodFor(browserTz) });
    }, (e) => { setLocating(false); setError(e.message || tr("Couldn't get your location")); }, { enableHighAccuracy: false, timeout: 15000 });
  };
  const submit = async () => {
    setBusy(true); setError("");
    try { await onSave(draft); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const offsets = draft.offsets;
  return (
    <section className={full ? "place-setup" : "panel place-setup"}>
      {!full && <h2><MapPin size={18} aria-hidden />{" "}{tr("Where do you pray?")}</h2>}
      {!full && <p className="muted small">{tr("Prayer times are worked out on this device from your place; nothing is looked up online.")}</p>}
      <div className="place-pick">
        <label className="search">
          <Search size={16} aria-hidden />
          <input type="search" value={find} onChange={(e) => setFind(e.target.value)} placeholder={tr("Find your city")} aria-label={tr("Find your city")} />
        </label>
        <div className="place-chips">
          {matches.map((p) => (
            <button key={p.name} type="button" className={draft.place === p.name ? "active" : ""} aria-pressed={draft.place === p.name}
              onClick={() => set({ lat: p.lat, lng: p.lng, place: p.name, timezone: p.tz, method: p.method })}>
              {lang() === "bn" && p.bn ? p.bn : p.name}
            </button>
          ))}
        </div>
        {canLocate && (
          <button type="button" onClick={locate} disabled={locating}><MapPin size={16} />{" "}{locating ? tr("Finding you…") : tr("Use this device's location")}</button>
        )}
        <details className="manual-place">
          <summary>{tr("Enter coordinates")}</summary>
          <div className="tv-form-row">
            <label>{tr("Latitude")}<input type="number" step="0.0001" min={-90} max={90} value={draft.lat ?? ""}
              onChange={(e) => set({ lat: e.target.value === "" ? null : Number(e.target.value), place: draft.place || tr("My place"), timezone: draft.timezone ?? browserTz })} /></label>
            <label>{tr("Longitude")}<input type="number" step="0.0001" min={-180} max={180} value={draft.lng ?? ""}
              onChange={(e) => set({ lng: e.target.value === "" ? null : Number(e.target.value), place: draft.place || tr("My place"), timezone: draft.timezone ?? browserTz })} /></label>
            <label>{tr("Name")}<input value={draft.place} maxLength={120} onChange={(e) => set({ place: e.target.value })} /></label>
          </div>
        </details>
      </div>
      {draft.lat != null && draft.lng != null && (
        <p className="muted small"><MapPin size={14} aria-hidden /> {draft.place} · {digits(`${draft.lat.toFixed(4)}, ${draft.lng.toFixed(4)}`)}</p>
      )}
      <div className="tv-form-row">
        <label>{tr("Calculation method")}
          <select value={draft.method} onChange={(e) => set({ method: e.target.value as Method })}>
            {(Object.keys(METHODS) as Method[]).map((m) => <option key={m} value={m}>{methodLabel(m)}</option>)}
          </select>
        </label>
        <label>{tr("Asr")}
          <select value={draft.asr} onChange={(e) => set({ asr: e.target.value as PrayerSettings["asr"] })}>
            <option value="hanafi">{tr("Hanafi (later)")}</option>
            <option value="standard">{tr("Shafi'i, Maliki, Hanbali (earlier)")}</option>
          </select>
        </label>
      </div>
      {full && (
        <>
          <details>
            <summary>{tr("Adjust times by a few minutes")}</summary>
            <p className="muted small">{tr("To match your mosque's timetable. Minutes later (or earlier with a minus).")}</p>
            <div className="offsets">
              {PRAYERS.map((p) => (
                <label key={p}>{prayerLabel(p)}
                  <input type="number" min={-60} max={60} value={offsets[p]}
                    onChange={(e) => set({ offsets: { ...offsets, [p]: Math.max(-60, Math.min(60, Number(e.target.value) || 0)) } })} />
                </label>
              ))}
            </div>
          </details>
          <details>
            <summary>{tr("Far north or south")}</summary>
            <label>{tr("When Fajr or Isha can't be worked out")}
              <select value={draft.high_lat} onChange={(e) => set({ high_lat: e.target.value as PrayerSettings["high_lat"] })}>
                <option value="angle">{tr("Part of the night by angle (recommended)")}</option>
                <option value="midnight">{tr("Middle of the night")}</option>
                <option value="seventh">{tr("One seventh of the night")}</option>
                <option value="none">{tr("No adjustment")}</option>
              </select>
            </label>
          </details>
          <details>
            <summary>{tr("Reminders on the phone app")}</summary>
            <p className="muted small">{tr("The ZiraHive Android app reminds you at these prayers, even when it's closed.")}</p>
            <div className="checks">
              {FARD.map((p) => (
                <label key={p} className="toggle-row"><input type="checkbox" checked={draft.reminders[p]}
                  onChange={(e) => set({ reminders: { ...draft.reminders, [p]: e.target.checked } })} /> {prayerLabel(p)}</label>
              ))}
            </div>
            <label>{tr("Remind me before the time (minutes)")}
              <input type="number" min={0} max={60} value={draft.reminders.before}
                onChange={(e) => set({ reminders: { ...draft.reminders, before: Math.max(0, Math.min(60, Number(e.target.value) || 0)) } })} />
            </label>
          </details>
        </>
      )}
      {error && <p className="error" role="alert">{error}</p>}
      <div className="admin-row">
        <button className="primary" onClick={() => void submit()} disabled={busy || draft.lat == null || draft.lng == null}>{busy ? tr("Saving…") : tr("Save")}</button>
      </div>
    </section>
  );
}

function methodLabel(m: Method): string {
  switch (m) {
    case "karachi": return tr("Karachi (Bangladesh, Pakistan, India)");
    case "mwl": return tr("Muslim World League (Europe)");
    case "isna": return tr("ISNA (North America)");
    case "makkah": return tr("Umm al-Qura (Saudi Arabia)");
    case "egypt": return tr("Egypt");
    case "dubai": return tr("Dubai (Gulf)");
    case "singapore": return tr("Singapore, Malaysia, Indonesia");
    case "turkey": return tr("Diyanet (Turkey)");
    case "tehran": return tr("Tehran");
    case "jafari": return tr("Jafari (Shia)");
  }
}

function NamazToday({ s, now }: { s: PrayerSettings; now: Date }) {
  const m = momentAt(now, s);
  const today = dateIn(now, s.timezone);
  const friday = today.weekday === 5;
  const h = hijri(now, lang() === "bn" ? "bn" : "en", s.timezone);
  const ramadan = h.month === 9;
  const dateText = new Intl.DateTimeFormat(locale() ?? "en", { weekday: "long", day: "numeric", month: "long", timeZone: s.timezone ?? undefined }).format(now);
  const label = (p: PrayerName) => (p === "dhuhr" && friday ? prayerLabel("jumuah") : prayerLabel(p));
  const dir = qibla(s.lat!, s.lng!);
  return (
    <>
      <section className="panel namaz-now">
        <div className="namaz-date">
          <span>{dateText}</span>
          {h.text && <span className="muted">{h.text}</span>}
          <span className="muted small"><MapPin size={13} aria-hidden /> {s.place || digits(`${s.lat}, ${s.lng}`)}</span>
        </div>
        <div className="namaz-count" aria-live="off">
          <span className="muted">{tr("{prayer} in", { prayer: label(m.next) })}</span>
          <strong className="big-count">{countdown(m.nextAt.getTime() - now.getTime())}</strong>
          <span className="muted small">{timeText(m.nextAt, s.timezone)}</span>
        </div>
        {m.current && m.endsAt && (
          <p className="namaz-current">
            {tr("Now: {prayer}. Its time ends in {time}.", { prayer: label(m.current), time: countdown(m.endsAt.getTime() - now.getTime()) })}
          </p>
        )}
        {!m.current && <p className="namaz-current muted">{tr("No prayer is due until Dhuhr. Avoid praying just after sunrise.")}</p>}
      </section>

      {ramadan && (
        <section className="panel ramadan">
          <div><span className="muted small">{tr("Sehri ends")}</span><strong>{timeText(m.today.fajr, s.timezone)}</strong></div>
          <div><span className="muted small">{tr("Iftar")}</span><strong>{timeText(m.today.maghrib, s.timezone)}</strong></div>
        </section>
      )}

      <section className="panel">
        <h2>{tr("Today's times")}</h2>
        <ul className="prayer-times">
          {PRAYERS.map((p) => {
            const active = m.current === p;
            return (
              <li key={p} className={`${active ? "active" : ""} ${p === "sunrise" ? "sunrise" : ""}`}>
                <span>{label(p)}</span>
                <span className="pt-time">{timeText(m.today[p], s.timezone)}</span>
              </li>
            );
          })}
          <li className="night"><span>{tr("Middle of the night")}</span><span className="pt-time">{timeText(m.today.midnight, s.timezone)}</span></li>
          <li className="night"><span>{tr("Last third of the night (Tahajjud)")}</span><span className="pt-time">{timeText(m.today.lastThird, s.timezone)}</span></li>
        </ul>
        <p className="muted small">{methodLabel(s.method)} · {s.asr === "hanafi" ? tr("Asr: Hanafi") : tr("Asr: Shafi'i")}</p>
      </section>

      <Tracker s={s} now={now} m={m} />

      <section className="panel qibla">
        <h2><Compass size={18} aria-hidden />{" "}{tr("Qibla")}</h2>
        <div className="qibla-row">
          <svg viewBox="-50 -50 100 100" className="qibla-dial" role="img" aria-label={tr("Qibla is {deg}° from north", { deg: Math.round(dir) })}>
            <circle r="46" className="qd-ring" />
            <text y="-34" textAnchor="middle" className="qd-n">N</text>
            <g transform={`rotate(${dir})`}>
              <line y1="8" y2="-36" className="qd-needle" />
              <path d="M0,-42 L-6,-30 L6,-30 Z" className="qd-head" />
            </g>
            <circle r="3" className="qd-hub" />
          </svg>
          <div>
            <p><strong>{digits(`${Math.round(dir)}°`)}</strong> {tr("clockwise from north")}</p>
            <p className="muted small">{tr("{km} km to Makkah", { km: Math.round(distanceToMakkah(s.lat!, s.lng!)) })}</p>
            <p className="muted small">{tr("Face this way using a compass, with north at the top.")}</p>
          </div>
        </div>
      </section>
    </>
  );
}

// ---------------------------------------------------------------- tracker

type Status = PrayerStatus;
const STATUS: Status[] = ["ontime", "late", "missed"];

function statusLabel(st: Status): string {
  return st === "ontime" ? tr("On time") : st === "late" ? tr("Late (qaza)") : tr("Missed");
}

function Tracker({ s, now, m }: { s: PrayerSettings; now: Date; m: ReturnType<typeof momentAt> }) {
  const today = dateIn(now, s.timezone);
  const todayKey = dayKey(today);
  const start = dayKey(addDays(today, -29));
  const [log, setLog] = useState<Record<string, PrayerLogEntry>>({});
  const [error, setError] = useState("");
  useEffect(() => {
    api.prayerLog(start, todayKey).then((rows) => setLog(Object.fromEntries(rows.map((r) => [`${r.day}|${r.prayer}`, r]))))
      .catch((e) => setError((e as Error).message));
  }, [start, todayKey]);

  const entry = (day: string, p: string) => log[`${day}|${p}`];
  const mark = async (day: string, p: string, status: Status | null, jamaah = false) => {
    const k = `${day}|${p}`;
    const before = log[k];
    setLog((l) => {
      const n = { ...l };
      if (status) n[k] = { day, prayer: p, status, jamaah: jamaah && status !== "missed" }; else delete n[k];
      return n;
    });
    try { await api.setPrayer(day, p, status, jamaah); }
    catch (e) { setError((e as Error).message); setLog((l) => ({ ...l, ...(before ? { [k]: before } : {}) })); }
  };

  // a prayer whose time hasn't come yet today can't be marked
  const started = (p: (typeof FARD)[number]) => m.today[p].getTime() <= now.getTime();
  // within its time -> "on time" by default; after -> "late"
  const suggested = (p: (typeof FARD)[number]): Status => (m.current === p ? "ontime" : "late");

  const days = Array.from({ length: 7 }, (_, i) => addDays(today, i - 6));
  const stats = useMemo(() => {
    let prayed = 0, ontime = 0, jamaah = 0, streak = 0;
    for (let i = 0; i < 30; i++) {
      const d = dayKey(addDays(today, -i));
      for (const p of FARD) {
        const e = log[`${d}|${p}`];
        if (e && e.status !== "missed") { prayed++; if (e.status === "ontime") ontime++; if (e.jamaah) jamaah++; }
      }
    }
    // days in a row with all five prayed, counting back from today (today counts once it's complete)
    for (let i = 0; i < 400; i++) {
      const d = dayKey(addDays(today, -i));
      const all = FARD.every((p) => { const e = log[`${d}|${p}`]; return e && e.status !== "missed"; });
      if (all) streak++;
      else if (i > 0) break;
      if (i >= 29) break;
    }
    return { prayed, ontime, jamaah, streak };
  }, [log, todayKey]);  // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <section className="panel tracker">
      <h2>{tr("Tracker")}</h2>
      {error && <p className="error" role="alert">{error}</p>}
      <ul className="track-today">
        {FARD.map((p) => {
          const e = entry(todayKey, p);
          const open = started(p);
          return (
            <li key={p}>
              <span className="tt-name">{p === "dhuhr" && today.weekday === 5 ? prayerLabel("jumuah") : prayerLabel(p)}</span>
              {open ? (
                <div className="tt-choices" role="group" aria-label={prayerLabel(p)}>
                  {STATUS.map((st) => (
                    <button key={st} className={`tt-${st} ${e?.status === st ? "active" : ""}`} aria-pressed={e?.status === st}
                      onClick={() => void mark(todayKey, p, e?.status === st ? null : st, e?.jamaah ?? false)}
                      title={st === suggested(p) && !e ? tr("Suggested") : undefined}>
                      {statusLabel(st)}
                    </button>
                  ))}
                  <label className={`tt-jamaah ${e && e.status !== "missed" ? "" : "off"}`}>
                    <input type="checkbox" checked={!!e?.jamaah} disabled={!e || e.status === "missed"}
                      onChange={(ev) => e && void mark(todayKey, p, e.status, ev.target.checked)} /> {tr("In jamaah")}
                  </label>
                </div>
              ) : <span className="muted small">{tr("At {time}", { time: timeText(m.today[p], s.timezone) })}</span>}
            </li>
          );
        })}
      </ul>

      <div className="week-grid" role="table" aria-label={tr("Last 7 days")}>
        <div role="row" className="wg-row wg-head">
          <span role="columnheader" />
          {days.map((d) => (
            <span role="columnheader" key={dayKey(d)}>
              {new Intl.DateTimeFormat(locale() ?? "en", { weekday: "narrow", timeZone: "UTC" }).format(new Date(Date.UTC(d.y, d.m - 1, d.d)))}
            </span>
          ))}
        </div>
        {FARD.map((p) => (
          <div role="row" className="wg-row" key={p}>
            <span role="rowheader">{prayerLabel(p)}</span>
            {days.map((d) => {
              const e = entry(dayKey(d), p);
              return (
                <span role="cell" key={dayKey(d)} className={`wg-dot ${e ? `wg-${e.status}` : ""}`}
                  title={e ? statusLabel(e.status) + (e.jamaah ? ` · ${tr("In jamaah")}` : "") : tr("Not marked")}>
                  <span className="sr">{e ? statusLabel(e.status) : tr("Not marked")}</span>
                </span>
              );
            })}
          </div>
        ))}
        <p className="muted small wg-legend">
          <span className="wg-dot wg-ontime" /> {tr("On time")} <span className="wg-dot wg-late" /> {tr("Late (qaza)")} <span className="wg-dot wg-missed" /> {tr("Missed")}
        </p>
      </div>

      <div className="tracker-stats">
        <div><strong>{digits(String(stats.streak))}</strong><span className="muted small">{tr("days in a row, all five")}</span></div>
        <div><strong>{digits(`${Math.round((stats.prayed / 150) * 100)}%`)}</strong><span className="muted small">{tr("prayed, last 30 days")}</span></div>
        <div><strong>{digits(String(stats.ontime))}</strong><span className="muted small">{tr("on time, last 30 days")}</span></div>
        <div><strong>{digits(String(stats.jamaah))}</strong><span className="muted small">{tr("in jamaah, last 30 days")}</span></div>
      </div>
    </section>
  );
}

// ------------------------------------------------------- reminders while ZiraHive is open

const ALERT_KEY = "zirahive.prayerAlerts";

export function browserAlertsOn(): boolean {
  try { return localStorage.getItem(ALERT_KEY) === "1"; } catch { return false; }
}
export function setBrowserAlerts(on: boolean) {
  try { localStorage.setItem(ALERT_KEY, on ? "1" : "0"); } catch { /* ignore */ }
}

/** Mounted once in the app: a gentle chime and a message when a prayer time comes, while a page is open. */
export function PrayerAlerts() {
  const [s] = usePrayerSettings();
  const [show, setShow] = useState<string | null>(null);
  const last = useRef("");
  useEffect(() => {
    if (!s || s.lat == null || !browserAlertsOn()) return;
    const tick = () => {
      const now = new Date();
      const m = momentAt(now, s);
      if (!m.current) return;
      const at = m.today[m.current].getTime();
      const key = `${dayKey(dateIn(now, s.timezone))}|${m.current}`;
      if (now.getTime() - at < 60_000 && now.getTime() >= at && last.current !== key && s.reminders[m.current]) {
        last.current = key;
        const text = tr("It's time for {prayer}.", { prayer: prayerLabel(m.current) });
        setShow(text);
        chime();
        try { if ("Notification" in window && Notification.permission === "granted") new Notification(tr("ZiraHive"), { body: text }); } catch { /* not allowed here */ }
      }
    };
    tick();
    const id = window.setInterval(tick, 15_000);
    return () => window.clearInterval(id);
  }, [s]);
  if (!show) return null;
  return (
    <div className="prayer-alert" role="status">
      <span>{show}</span>
      <Link to="/quran/namaz" onClick={() => setShow(null)}>{tr("Open")}</Link>
      <button className="icon" onClick={() => setShow(null)} aria-label={tr("Close")}>×</button>
    </div>
  );
}

function chime() {
  try {
    const ctx = new AudioContext();
    const notes = [523.25, 659.25, 783.99];
    notes.forEach((f, i) => {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.type = "sine"; o.frequency.value = f;
      const t0 = ctx.currentTime + i * 0.35;
      g.gain.setValueAtTime(0, t0); g.gain.linearRampToValueAtTime(0.15, t0 + 0.05); g.gain.exponentialRampToValueAtTime(0.001, t0 + 1.2);
      o.connect(g).connect(ctx.destination); o.start(t0); o.stop(t0 + 1.3);
    });
    window.setTimeout(() => void ctx.close(), 2500);
  } catch { /* no sound here */ }
}

/** The toggle for in-browser reminders (on the Namaz page). */
export function BrowserAlertToggle() {
  const [on, setOn] = useState(browserAlertsOn());
  const toggle = async (v: boolean) => {
    setBrowserAlerts(v); setOn(v);
    if (v && "Notification" in window && Notification.permission === "default") {
      try { await Notification.requestPermission(); } catch { /* ignore */ }
    }
    window.dispatchEvent(new Event(SETTINGS_EVENT));
  };
  return (
    <label className="toggle-row">
      <input type="checkbox" checked={on} onChange={(e) => void toggle(e.target.checked)} />
      {" "}{tr("Chime in this browser at prayer times (while ZiraHive is open)")}
    </label>
  );
}
