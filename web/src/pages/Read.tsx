import { useEffect, useMemo, useState } from "react";
import { Link, NavLink, useParams, useSearchParams } from "react-router-dom";
import { ArrowLeft, Search } from "lucide-react";
import { api, url, type Book, type Library } from "../api";
import { useAuth } from "../App";
import { BookCard } from "./Listen";

const READ_KINDS = ["books", "comics"];

function useReadLibraries() {
  const [libs, setLibs] = useState<Library[] | null>(null);
  useEffect(() => { api.libraries().then((all) => setLibs(all.filter((l) => READ_KINDS.includes(l.kind)))).catch(() => setLibs([])); }, []);
  return libs;
}

function ReadTabs({ libs }: { libs: Library[] }) {
  return (
    <nav className="lib-tabs" aria-label="Reading categories">
      <NavLink to="/read" end>Home</NavLink>
      {libs.filter((l) => l.available && l.item_count > 0).map((l) => <NavLink key={l.id} to={`/read/c/${l.id}`}>{l.name}</NavLink>)}
    </nav>
  );
}

const readerLink = (b: Book) => `/read/book/${b.id}`;

/** Series with 2 or more books show as one tile. */
function group(books: Book[]): (Book | { series: string; books: Book[] })[] {
  const counts = new Map<string, number>();
  books.forEach((b) => { if (b.series_name) counts.set(b.series_name, (counts.get(b.series_name) ?? 0) + 1); });
  const out: (Book | { series: string; books: Book[] })[] = [];
  const seen = new Map<string, { series: string; books: Book[] }>();
  for (const b of books) {
    if (b.series_name && (counts.get(b.series_name) ?? 0) > 1) {
      let g = seen.get(b.series_name);
      if (!g) { g = { series: b.series_name, books: [] }; seen.set(b.series_name, g); out.push(g); }
      g.books.push(b);
    } else out.push(b);
  }
  out.forEach((x) => { if ("series" in x) x.books.sort((p, q) => (p.series_index ?? 0) - (q.series_index ?? 0)); });
  return out;
}

function SeriesCard({ series, books, libraryId }: { series: string; books: Book[]; libraryId: string }) {
  const first = books.find((b) => b.cover_ready) ?? books[0];
  const read = books.filter((b) => b.progress?.finished).length;
  return (
    <Link to={`/read/series?name=${encodeURIComponent(series)}&library=${libraryId}`} className="mtile book">
      <div className="cover tall stack">
        {first.cover_ready ? <img src={url.bookCover(first)} alt="" loading="lazy" /> : <span className="cover-blank">{series}</span>}
        <span className="poster-flag">{books.length}</span>
      </div>
      <span className="poster-title">{series}</span>
      <span className="poster-meta">{books.length} books{read ? `, ${read} read` : ""}</span>
    </Link>
  );
}

export function ReadHome() {
  const { user } = useAuth();
  const libs = useReadLibraries();
  const [cont, setCont] = useState<Book[]>([]);
  const [shelves, setShelves] = useState<Record<string, Book[]>>({});
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Book[] | null>(null);
  useEffect(() => { api.continueBooks("reading").then(setCont).catch(() => undefined); }, []);
  useEffect(() => {
    libs?.filter((l) => l.item_count > 0).forEach((l) => {
      api.books({ library_id: l.id, limit: 24 }).then((b) => setShelves((s) => ({ ...s, [l.id]: b }))).catch(() => undefined);
    });
  }, [libs]);
  useEffect(() => {
    if (!query.trim()) { setResults(null); return; }
    const t = setTimeout(() => { api.books({ kind: "reading", q: query.trim(), sort: "title" }).then(setResults).catch(() => undefined); }, 250);
    return () => clearTimeout(t);
  }, [query]);
  const visible = libs?.filter((l) => l.available && l.item_count > 0) ?? [];
  return (
    <div className="page read-page">
      <header className="page-head"><h1>Read</h1></header>
      <div className="watch-bar">
        {libs && <ReadTabs libs={libs} />}
        <label className="search"><Search size={17} aria-hidden />
          <input placeholder="Search books and comics" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search books and comics" /></label>
      </div>
      {results && (results.length === 0 ? <p className="muted">Nothing matches "{query}".</p>
        : <div className="mtile-grid books">{results.map((b) => <BookCard key={b.id} b={b} to={readerLink(b)} />)}</div>)}
      {!results && <>
        {cont.length > 0 && (
          <section className="shelf-block">
            <h2 className="shelf-title">Continue reading</h2>
            <div className="shelf">{cont.map((b) => <BookCard key={b.id} b={b} to={readerLink(b)} />)}</div>
          </section>
        )}
        {visible.map((l) => (
          <section key={l.id} className="shelf-block">
            <Link to={`/read/c/${l.id}`} className="shelf-title link">{l.name} <span className="count">{l.item_count}</span></Link>
            <div className="shelf">{(shelves[l.id] ?? []).map((b) => <BookCard key={b.id} b={b} to={readerLink(b)} />)}</div>
          </section>
        ))}
        {libs && visible.length === 0 && (
          <div className="empty">
            <h2>Nothing to read yet</h2>
            {user.is_admin
              ? <p>Put EPUB and PDF books in a folder called Ebooks, and comics (CBZ, CBR, or folders of pages) in a folder called Comics,
                  inside your media folder. Then open <Link to="/settings">Settings</Link> and press Find new folders.</p>
              : <p>Ask the admin to add book and comic folders.</p>}
          </div>
        )}
      </>}
    </div>
  );
}

export function ReadLibraryPage() {
  const { id } = useParams();
  const libs = useReadLibraries();
  const lib = libs?.find((l) => l.id === id);
  const [books, setBooks] = useState<Book[] | null>(null);
  const [sort, setSort] = useState<"added" | "title" | "author" | "series">("added");
  const [filter, setFilter] = useState("");
  const [grouped, setGrouped] = useState(true);
  useEffect(() => { if (id) { setBooks(null); api.books({ library_id: id, sort }).then(setBooks).catch(() => setBooks([])); } }, [id, sort]);
  const shown = useMemo(() => books?.filter((b) => !filter || `${b.title} ${b.author ?? ""} ${b.series_name ?? ""}`.toLowerCase().includes(filter.toLowerCase())), [books, filter]);
  const items = shown ? (grouped && !filter ? group(shown) : shown) : null;
  return (
    <div className="page read-page">
      <header className="page-head"><h1>{lib?.name ?? "Read"}</h1></header>
      {libs && <ReadTabs libs={libs} />}
      <div className="lib-tools">
        <label className="search"><Search size={17} aria-hidden />
          <input placeholder={`Search ${lib?.name ?? ""}`} value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Search this category" /></label>
        <label className="sort">Sort by
          <select value={sort} onChange={(e) => setSort(e.target.value as typeof sort)}>
            <option value="added">Recently added</option><option value="title">Title</option>
            <option value="author">Author</option><option value="series">Series</option>
          </select>
        </label>
        <label className="check"><input type="checkbox" checked={grouped} onChange={(e) => setGrouped(e.target.checked)} /> Group series</label>
      </div>
      {shown?.length === 0 && <p className="muted">{filter ? `Nothing matches "${filter}".` : "This category is empty."}</p>}
      <div className="mtile-grid books">
        {items?.map((x) => ("series" in x
          ? <SeriesCard key={`s-${x.series}`} series={x.series} books={x.books} libraryId={id!} />
          : <BookCard key={x.id} b={x} to={readerLink(x)} />))}
      </div>
    </div>
  );
}

export function ReadSeriesPage() {
  const [params] = useSearchParams();
  const name = params.get("name") ?? "";
  const library = params.get("library") ?? undefined;
  const [books, setBooks] = useState<Book[] | null>(null);
  useEffect(() => { api.books({ series: name, library_id: library }).then(setBooks).catch(() => setBooks([])); }, [name, library]);
  const next = books?.find((b) => !b.progress?.finished);
  return (
    <div className="page read-page">
      <Link to={library ? `/read/c/${library}` : "/read"} className="back"><ArrowLeft size={18} /> Back</Link>
      <header className="page-head"><h1>{name}</h1>
        {next && <Link className="button primary" to={readerLink(next)}>{next.progress?.fraction ? "Continue" : "Start"} with {next.title}</Link>}
      </header>
      <div className="mtile-grid books">{books?.map((b) => <BookCard key={b.id} b={b} to={readerLink(b)} />)}</div>
    </div>
  );
}
