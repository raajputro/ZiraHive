import { useEffect, useState } from "react";
import { Link, NavLink, useParams } from "react-router-dom";
import { Search, ChevronRight } from "lucide-react";
import { api, url, episodeCode, formatDuration, VIDEO_KINDS, type Library, type Media, type Title } from "../api";
import { useAuth } from "../App";

/** Category tabs shared by every Watch page: Home, English Movies, Web Series, ... */
export function WatchTabs({ libraries, query, onQuery }:
  { libraries: Library[]; query?: string; onQuery?: (q: string) => void }) {
  return (
    <div className="watch-bar">
      <nav className="lib-tabs" aria-label="Categories">
        <NavLink to="/watch" end>Home</NavLink>
        <NavLink to="/watch/parties">Watch parties</NavLink>
        {libraries.filter((l) => l.available && l.item_count > 0 && VIDEO_KINDS.includes(l.kind)).map((l) => (
          <NavLink key={l.id} to={`/watch/c/${l.id}`}>{l.name}</NavLink>
        ))}
      </nav>
      {onQuery && (
        <label className="search">
          <Search size={17} aria-hidden />
          <input placeholder="Search everything" value={query} onChange={(e) => onQuery(e.target.value)} aria-label="Search movies and series" />
        </label>
      )}
    </div>
  );
}

export function TitleCard({ t }: { t: Title }) {
  const to = t.type === "series" ? `/watch/series/${t.id}` : `/play/${t.id}`;
  const pct = t.type === "movie"
    ? (t.duration && t.position && !t.finished ? Math.min(100, (t.position / t.duration) * 100) : 0)
    : (t.episode_count ? (t.watched_count / t.episode_count) * 100 : 0);
  const meta = t.type === "series"
    ? [t.year, `${t.episode_count} episode${t.episode_count === 1 ? "" : "s"}`]
    : [t.year, formatDuration(t.duration)];
  return (
    <Link to={to} className="poster">
      <div className="poster-art">
        {t.poster_ready ? <img src={url.titlePoster(t)} alt="" loading="lazy" /> : <span className="poster-blank">{t.title}</span>}
        {t.type === "series" && <span className="poster-flag">Series</span>}
        {pct > 0 && <span className="poster-progress"><span style={{ width: `${pct}%` }} /></span>}
      </div>
      <span className="poster-title">{t.title}</span>
      <span className="poster-meta">{meta.filter(Boolean).join(", ")}</span>
    </Link>
  );
}

function ContinueCard({ m }: { m: Media }) {
  const pct = m.duration && m.position ? Math.min(100, (m.position / m.duration) * 100) : 0;
  const isEpisode = !!m.series_id;
  return (
    <Link to={`/play/${m.id}`} className="still">
      <div className="still-art">
        {m.poster_ready ? <img src={url.poster(m)} alt="" loading="lazy" /> : <span className="poster-blank">{m.title}</span>}
        <span className="poster-progress"><span style={{ width: `${pct}%` }} /></span>
      </div>
      <span className="poster-title">{isEpisode ? m.series_title : m.title}</span>
      <span className="poster-meta">
        {isEpisode ? `${episodeCode(m)}${m.position < 5 ? ", up next" : ""}` : `${formatDuration((m.duration ?? 0) - m.position)} left`}
      </span>
    </Link>
  );
}

function useLibraries() {
  const [libs, setLibs] = useState<Library[] | null>(null);
  useEffect(() => { api.libraries().then((all) => setLibs(all.filter((l) => VIDEO_KINDS.includes(l.kind)))).catch(() => setLibs([])); }, []);
  return libs;
}

export default function WatchHome() {
  const { user } = useAuth();
  const libs = useLibraries();
  const [shelves, setShelves] = useState<Record<string, Title[]>>({});
  const [resume, setResume] = useState<Media[]>([]);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Title[] | null>(null);

  useEffect(() => { api.continueWatching().then(setResume).catch(() => undefined); }, []);
  useEffect(() => {
    if (!libs) return;
    libs.filter((l) => l.available && l.item_count > 0).forEach((l) => {
      api.titles({ library_id: l.id, limit: 24 }).then((t) => setShelves((s) => ({ ...s, [l.id]: t }))).catch(() => undefined);
    });
  }, [libs]);
  useEffect(() => {
    if (!query.trim()) { setResults(null); return; }
    const t = setTimeout(() => { api.titles({ q: query.trim(), sort: "title" }).then(setResults).catch(() => undefined); }, 250);
    return () => clearTimeout(t);
  }, [query]);

  const visible = libs?.filter((l) => l.available && l.item_count > 0) ?? [];

  return (
    <div className="page cinema-page">
      <header className="page-head"><h1>Watch</h1></header>
      {libs && <WatchTabs libraries={libs} query={query} onQuery={setQuery} />}

      {results && (
        <section>
          {results.length === 0
            ? <p className="muted">Nothing matches "{query}".</p>
            : <div className="poster-grid">{results.map((t) => <TitleCard key={t.id} t={t} />)}</div>}
        </section>
      )}

      {!results && <>
        {resume.length > 0 && (
          <section className="shelf-block">
            <h2 className="shelf-title">Continue watching</h2>
            <div className="shelf stills">{resume.map((m) => <ContinueCard key={m.id} m={m} />)}</div>
          </section>
        )}
        {visible.map((l) => (
          <section key={l.id} className="shelf-block">
            <Link to={`/watch/c/${l.id}`} className="shelf-title link">
              {l.name} <span className="count">{l.item_count}</span> <ChevronRight size={18} aria-hidden />
            </Link>
            <div className="shelf">{(shelves[l.id] ?? []).map((t) => <TitleCard key={t.id} t={t} />)}</div>
          </section>
        ))}
        {libs && visible.length === 0 && (
          <div className="empty">
            <h2>Nothing to watch yet</h2>
            {user.is_admin ? (
              <p>Make one folder per category inside your media folder, such as English Movies, Hindi Movies,
                Bangla Movies, Web Series and Animation. Then open <Link to="/settings">Settings</Link> and press
                Find new folders.</p>
            ) : <p>Ask the admin to add movie and series folders.</p>}
          </div>
        )}
      </>}
    </div>
  );
}

export function LibraryPage() {
  const { id } = useParams();
  const libs = useLibraries();
  const [titles, setTitles] = useState<Title[] | null>(null);
  const [sort, setSort] = useState<"added" | "title" | "year">("added");
  const [filter, setFilter] = useState("");
  const lib = libs?.find((l) => l.id === id);

  useEffect(() => {
    if (!id) return;
    setTitles(null);
    api.titles({ library_id: id, sort }).then(setTitles).catch(() => setTitles([]));
  }, [id, sort]);

  const shown = titles?.filter((t) => !filter || t.title.toLowerCase().includes(filter.toLowerCase()));

  return (
    <div className="page cinema-page">
      <header className="page-head"><h1>{lib?.name ?? "Watch"}</h1></header>
      {libs && <WatchTabs libraries={libs} />}
      <div className="lib-tools">
        <label className="search">
          <Search size={17} aria-hidden />
          <input placeholder={`Search ${lib?.name ?? ""}`} value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Search this category" />
        </label>
        <label className="sort">Sort by
          <select value={sort} onChange={(e) => setSort(e.target.value as typeof sort)}>
            <option value="added">Recently added</option>
            <option value="title">Title</option>
            <option value="year">Newest release</option>
          </select>
        </label>
      </div>
      {shown && shown.length === 0 && <p className="muted">{filter ? `Nothing matches "${filter}".` : "This category is empty."}</p>}
      {shown && shown.length > 0 && <div className="poster-grid">{shown.map((t) => <TitleCard key={t.id} t={t} />)}</div>}
    </div>
  );
}
