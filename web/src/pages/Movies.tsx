import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Search } from "lucide-react";
import { api, url, formatDuration, type Media } from "../api";
import { useAuth } from "../App";

function Poster({ m }: { m: Media }) {
  const pct = m.duration && m.position ? Math.min(100, (m.position / m.duration) * 100) : 0;
  return (
    <Link to={`/watch/${m.id}`} className="poster">
      <div className="poster-art">
        {m.poster_ready ? <img src={url.poster(m)} alt="" loading="lazy" /> : <span className="poster-blank">{m.title}</span>}
        {pct > 0 && !m.finished && <span className="poster-progress"><span style={{ width: `${pct}%` }} /></span>}
      </div>
      <span className="poster-title">{m.title}</span>
      <span className="poster-meta">{[m.year, formatDuration(m.duration)].filter(Boolean).join(", ")}</span>
    </Link>
  );
}

export default function MoviesPage() {
  const { user } = useAuth();
  const [items, setItems] = useState<Media[] | null>(null);
  const [resume, setResume] = useState<Media[]>([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    const t = setTimeout(() => {
      api.media(query).then(setItems).catch((e) => setError(e.message));
    }, query ? 250 : 0);
    return () => clearTimeout(t);
  }, [query]);
  useEffect(() => { api.continueWatching().then(setResume).catch(() => undefined); }, []);

  return (
    <div className="page cinema-page">
      <header className="page-head">
        <h1>Movies</h1>
        <label className="search">
          <Search size={17} aria-hidden />
          <input placeholder="Search titles" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search movies" />
        </label>
      </header>
      {error && <p className="error" role="alert">{error}</p>}
      {resume.length > 0 && !query && (
        <section>
          <h2 className="shelf-title">Continue watching</h2>
          <div className="shelf">{resume.map((m) => <Poster key={m.id} m={m} />)}</div>
        </section>
      )}
      {items && items.length === 0 && !query && (
        <div className="empty">
          <h2>Your movie shelf is empty</h2>
          <p>{user.is_admin
            ? <>Point GharBox at your movie folder in <Link to="/settings">Settings</Link>, or set MOVIES_PATH in the .env file.</>
            : "Ask the admin to add a movie folder."}</p>
        </div>
      )}
      {items && items.length === 0 && query && <p className="muted">No titles match "{query}".</p>}
      {items && items.length > 0 && (
        <section>
          {!query && <h2 className="shelf-title">All movies</h2>}
          <div className="poster-grid">{items.map((m) => <Poster key={m.id} m={m} />)}</div>
        </section>
      )}
    </div>
  );
}
