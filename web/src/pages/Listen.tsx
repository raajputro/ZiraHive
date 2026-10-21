import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, NavLink, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ArrowLeft, ArrowDown, ArrowUp, Heart, ListPlus, MoreVertical, Music, Pause, Play, Plus, Search, Shuffle, Trash2, Headphones, RotateCcw } from "lucide-react";
import { api, ApiError, url, type Artist, type ArtistDetail, type Book, type BookDetail, type MusicAlbum, type MusicAlbumDetail,
  type MusicHome, type Playlist, type PlaylistDetail, type Track } from "../api";
import { clock, useAudio } from "../audio";
import Dialog from "../components/Dialog";
import { EqualizerButton } from "../components/Equalizer";

import { t as tr } from "../i18n";
// ---------------------------------------------------------------- shared bits

export function ListenTabs() {
  return (
    <nav className="lib-tabs" aria-label={tr("Listen")}>
      <NavLink to="/listen" end>{tr("Home")}</NavLink>
      <NavLink to="/listen/albums">{tr("Albums")}</NavLink>
      <NavLink to="/listen/artists">{tr("Artists")}</NavLink>
      <NavLink to="/listen/songs">{tr("Songs")}</NavLink>
      <NavLink to="/listen/playlists">{tr("Playlists")}</NavLink>
      <NavLink to="/listen/audiobooks">{tr("Audiobooks")}</NavLink>
    </nav>
  );
}

function hours(sec: number): string {
  if (!sec) return "";
  if (sec < 60) return `${Math.round(sec)} s`;
  const h = Math.floor(sec / 3600), m = Math.round((sec % 3600) / 60);
  return h ? `${h} h ${m} min` : `${m} min`;
}

function Cover({ src, label, round = false }: { src: string | null; label: string; round?: boolean }) {
  return (
    <div className={`cover ${round ? "round" : ""}`}>
      {src ? <img src={src} alt="" loading="lazy" /> : <span className="cover-blank" aria-hidden>{label.slice(0, 1).toUpperCase()}</span>}
    </div>
  );
}

function AlbumCard({ a }: { a: MusicAlbum }) {
  return (
    <Link to={`/listen/album/${a.id}`} className="mtile">
      <Cover src={a.cover_ready ? url.albumCover(a) : null} label={a.title} />
      <span className="poster-title">{a.title}</span>
      <span className="poster-meta">{[a.artist, a.year].filter(Boolean).join(", ")}</span>
    </Link>
  );
}

export function BookCard({ b, to }: { b: Book; to: string }) {
  const pct = b.progress ? Math.round(b.progress.fraction * 100) : 0;
  return (
    <Link to={to} className="mtile book">
      <div className="cover tall">
        {b.cover_ready ? <img src={url.bookCover(b)} alt="" loading="lazy" /> : <span className="cover-blank">{b.title}</span>}
        {pct > 0 && !b.progress?.finished && <span className="poster-progress"><span style={{ width: `${pct}%` }} /></span>}
        {b.progress?.finished && <span className="poster-flag">{tr("Finished")}</span>}
      </div>
      <span className="poster-title">{b.title}</span>
      <span className="poster-meta">{b.author ?? (b.series_name ? `${b.series_name}` : "")}</span>
    </Link>
  );
}

function PlayButtons({ tracks }: { tracks: Track[] }) {
  const a = useAudio();
  if (!tracks.length) return null;
  return (
    <>
      <button className="primary" onClick={() => a.playTracks(tracks)}><Play size={17} fill="currentColor" />{" "}{tr("Play")}</button>
      <button onClick={() => a.playTracks(tracks, 0, true)}><Shuffle size={17} />{" "}{tr("Shuffle")}</button>
    </>
  );
}

export function TrackList({ tracks, numbered = false, showAlbum = true, onRemove, onMove }: {
  tracks: Track[]; numbered?: boolean; showAlbum?: boolean;
  onRemove?: (i: number) => void; onMove?: (i: number, d: -1 | 1) => void;
}) {
  const a = useAudio();
  const [favs, setFavs] = useState<Record<string, boolean>>({});
  const [menu, setMenu] = useState<number | null>(null);
  const [adding, setAdding] = useState<Track[] | null>(null);
  const fav = (t: Track) => favs[t.id] ?? t.favorite;
  const toggleFav = async (t: Track) => {
    const v = !fav(t);
    setFavs((f) => ({ ...f, [t.id]: v }));
    await api.setFavorite(t.id, v).catch(() => setFavs((f) => ({ ...f, [t.id]: !v })));
  };
  return (
    <>
      <ol className="tracks">
        {tracks.map((t, i) => {
          const now = a.current?.kind === "track" && a.current.id === t.id;
          return (
            <li key={`${t.id}-${i}`} className={now ? "now" : ""}>
              <button className="track-main" onClick={() => (now ? a.toggle() : a.playTracks(tracks, i))}
                aria-label={now && a.playing ? tr("Pause {title}", { title: t.title }) : tr("Play {title}", { title: t.title })}>
                <span className="track-no">{now ? (a.playing ? <Pause size={14} /> : <Play size={14} />) : numbered ? (t.track_no ?? i + 1) : i + 1}</span>
                <span className="track-text">
                  <span className="track-title">{t.title}{!t.playable && <span className="tag" title={tr("Converted for the browser the first time it plays")}>{tr("converts")}</span>}</span>
                  <span className="muted small">{[t.artist, showAlbum ? t.album_title : null].filter(Boolean).join(" · ")}</span>
                </span>
                <span className="muted small track-dur">{clock(t.duration)}</span>
              </button>
              {!t.quran && <>
              <button className={`icon ${fav(t) ? "fav" : ""}`} onClick={() => void toggleFav(t)} aria-pressed={fav(t)}
                aria-label={fav(t) ? tr("Remove {title} from favourites", { title: t.title }) : tr("Add {title} to favourites", { title: t.title })}>
                <Heart size={16} fill={fav(t) ? "currentColor" : "none"} />
              </button>
              <div className="menu-wrap">
                <button className="icon" onClick={() => setMenu(menu === i ? null : i)} aria-label={tr("More for {title}", { title: t.title })} aria-expanded={menu === i}>
                  <MoreVertical size={16} />
                </button>
                {menu === i && (
                  <div className="menu" role="menu" onClick={() => setMenu(null)}>
                    <button role="menuitem" onClick={() => a.playNext([t])}>{tr("Play next")}</button>
                    <button role="menuitem" onClick={() => a.addToQueue([t])}>{tr("Add to queue")}</button>
                    <button role="menuitem" onClick={() => setAdding([t])}>{tr("Add to playlist…")}</button>
                    {t.album_id && <Link role="menuitem" to={`/listen/album/${t.album_id}`}>{tr("Go to album")}</Link>}
                    {t.artist && <Link role="menuitem" to={`/listen/artist?name=${encodeURIComponent(t.artist)}`}>{tr("Go to artist")}</Link>}
                    {onMove && i > 0 && <button role="menuitem" onClick={() => onMove(i, -1)}><ArrowUp size={14} />{" "}{tr("Move up")}</button>}
                    {onMove && i < tracks.length - 1 && <button role="menuitem" onClick={() => onMove(i, 1)}><ArrowDown size={14} />{" "}{tr("Move down")}</button>}
                    {onRemove && <button role="menuitem" className="danger-text" onClick={() => onRemove(i)}>{tr("Remove from playlist")}</button>}
                  </div>
                )}
              </div>
              </>}
            </li>
          );
        })}
      </ol>
      {adding && <AddToPlaylist tracks={adding} onClose={() => setAdding(null)} />}
    </>
  );
}

function AddToPlaylist({ tracks, onClose }: { tracks: Track[]; onClose: () => void }) {
  const [lists, setLists] = useState<Playlist[]>([]);
  const [name, setName] = useState("");
  const [done, setDone] = useState("");
  useEffect(() => { api.playlists().then(setLists).catch(() => undefined); }, []);
  const ids = tracks.map((t) => t.id);
  const what = tracks.length === 1 ? tracks[0].title : `${tracks.length} songs`;
  const add = async (p: Playlist) => { await api.addToPlaylist(p.id, ids); setDone(tr("Added {what} to {name}.", { what: what, name: p.name })); };
  const create = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    const p = await api.createPlaylist(name.trim(), ids);
    setDone(tr("Made {name} with {what}.", { name: p.name, what: what }));
  };
  return (
    <Dialog title={tr("Add to playlist")} onClose={onClose}>
      {done ? <><p role="status">{done}</p><button className="primary" onClick={onClose}>{tr("Done")}</button></> : (
        <div className="stack-form">
          {lists.length > 0 && (
            <ul className="pick-list">
              {lists.map((p) => <li key={p.id}><button onClick={() => void add(p)}><ListPlus size={16} /> {p.name} <span className="muted small">{p.track_count}{" "}{tr("songs")}</span></button></li>)}
            </ul>
          )}
          <form className="admin-row" onSubmit={create}>
            <label>{tr("New playlist")}<input value={name} onChange={(e) => setName(e.target.value)} maxLength={128} placeholder={tr("Name")} /></label>
            <button className="primary" disabled={!name.trim()}><Plus size={16} />{" "}{tr("Create")}</button>
          </form>
        </div>
      )}
    </Dialog>
  );
}

function Page({ title, children, back }: { title: string; children: React.ReactNode; back?: { to: string; label: string } }) {
  return (
    <div className="page cinema-page listen-page">
      {back && <Link to={back.to} className="back"><ArrowLeft size={18} /> {back.label}</Link>}
      <header className="page-head"><h1>{title}</h1><div className="head-actions"><EqualizerButton /></div></header>
      <ListenTabs />
      {children}
    </div>
  );
}

// -------------------------------------------------------------------- home

export function ListenHome() {
  const [home, setHome] = useState<MusicHome | null>(null);
  const [books, setBooks] = useState<Book[]>([]);
  const [listening, setListening] = useState<Book[]>([]);
  useEffect(() => {
    api.musicHome().then(setHome).catch(() => undefined);
    api.books({ kind: "audiobook", limit: 18 }).then(setBooks).catch(() => undefined);
    api.continueBooks("audiobook").then(setListening).catch(() => undefined);
  }, []);
  const nothing = home && !home.recent_albums.length && !books.length;
  return (
    <Page title={tr("Listen")}>
      {listening.length > 0 && (
        <section className="shelf-block">
          <h2 className="shelf-title">{tr("Continue listening")}</h2>
          <div className="shelf">{listening.map((b) => <BookCard key={b.id} b={b} to={`/listen/book/${b.id}`} />)}</div>
        </section>
      )}
      {home && home.recently_played.length > 0 && (
        <section className="shelf-block">
          <h2 className="shelf-title">{tr("Recently played")}</h2>
          <TrackList tracks={home.recently_played.slice(0, 6)} />
        </section>
      )}
      {home && home.recent_albums.length > 0 && (
        <section className="shelf-block">
          <Link to="/listen/albums" className="shelf-title link">{tr("Recently added")}</Link>
          <div className="shelf">{home.recent_albums.map((a) => <AlbumCard key={a.id} a={a} />)}</div>
        </section>
      )}
      {home && (home.playlists.length > 0 || home.favorite_count > 0) && (
        <section className="shelf-block">
          <Link to="/listen/playlists" className="shelf-title link">{tr("Your playlists")}</Link>
          <div className="shelf">
            {home.favorite_count > 0 && <FavoritesTile count={home.favorite_count} />}
            {home.playlists.map((p) => <PlaylistTile key={p.id} p={p} />)}
          </div>
        </section>
      )}
      {home && home.most_played.length > 0 && (
        <section className="shelf-block">
          <h2 className="shelf-title">{tr("Most played")}</h2>
          <TrackList tracks={home.most_played.slice(0, 6)} />
        </section>
      )}
      {books.length > 0 && (
        <section className="shelf-block">
          <Link to="/listen/audiobooks" className="shelf-title link">{tr("Audiobooks")}</Link>
          <div className="shelf">{books.map((b) => <BookCard key={b.id} b={b} to={`/listen/book/${b.id}`} />)}</div>
        </section>
      )}
      {nothing && (
        <div className="empty">
          <h2>{tr("Nothing to listen to yet")}</h2>
          <p>{tr("Put music in a folder called Music, and audiobooks in a folder called Audiobooks, inside your media folder. Then open Settings and press Find new folders. Artist and album folders work, and so do the tags inside the files.")}</p>
        </div>
      )}
    </Page>
  );
}

function FavoritesTile({ count }: { count: number }) {
  return (
    <Link to="/listen/songs?favorites=1" className="mtile">
      <div className="cover fav-cover"><Heart size={40} fill="currentColor" /></div>
      <span className="poster-title">{tr("Favourites")}</span>
      <span className="poster-meta">{count} {count === 1 ? "song" : "songs"}</span>
    </Link>
  );
}

function PlaylistTile({ p }: { p: Playlist }) {
  return (
    <Link to={`/listen/playlist/${p.id}`} className="mtile">
      <div className={`cover mosaic n${Math.min(4, p.cover_album_ids.length)}`}>
        {p.cover_album_ids.length ? p.cover_album_ids.slice(0, 4).map((id) => <img key={id} src={url.albumCover({ id })} alt="" loading="lazy" />)
          : <span className="cover-blank"><Music size={36} /></span>}
      </div>
      <span className="poster-title">{p.name}</span>
      <span className="poster-meta">{p.track_count} {p.track_count === 1 ? "song" : "songs"}</span>
    </Link>
  );
}

// ------------------------------------------------------------- albums, artists

export function AlbumsPage() {
  const [albums, setAlbums] = useState<MusicAlbum[] | null>(null);
  const [sort, setSort] = useState<"added" | "title" | "artist" | "year">("added");
  const [filter, setFilter] = useState("");
  useEffect(() => { api.musicAlbums({ sort }).then(setAlbums).catch(() => setAlbums([])); }, [sort]);
  const shown = albums?.filter((a) => !filter || `${a.title} ${a.artist}`.toLowerCase().includes(filter.toLowerCase()));
  return (
    <Page title={tr("Albums")}>
      <div className="lib-tools">
        <label className="search"><Search size={17} aria-hidden />
          <input placeholder={tr("Search albums")} value={filter} onChange={(e) => setFilter(e.target.value)} aria-label={tr("Search albums")} /></label>
        <label className="sort">{tr("Sort by")}<select value={sort} onChange={(e) => setSort(e.target.value as typeof sort)}>
            <option value="added">{tr("Recently added")}</option><option value="title">{tr("Title")}</option>
            <option value="artist">{tr("Artist")}</option><option value="year">{tr("Newest")}</option>
          </select>
        </label>
      </div>
      {shown?.length === 0 && <p className="muted">{filter ? tr("Nothing matches \"{filter}\".", { filter: filter }) : tr("No albums yet.")}</p>}
      <div className="mtile-grid">{shown?.map((a) => <AlbumCard key={a.id} a={a} />)}</div>
    </Page>
  );
}

export function AlbumDetailPage() {
  const { id } = useParams();
  const [album, setAlbum] = useState<MusicAlbumDetail | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { if (id) api.musicAlbum(id).then(setAlbum).catch((e) => setError(e.message)); }, [id]);
  if (error) return <Page title={tr("Album")}><p className="error">{error}</p></Page>;
  if (!album) return <div className="page cinema-page" aria-busy="true" />;
  const discs = new Set(album.tracks.map((t) => t.disc_no ?? 1)).size > 1;
  return (
    <div className="page cinema-page listen-page">
      <Link to="/listen/albums" className="back"><ArrowLeft size={18} />{" "}{tr("Albums")}</Link>
      <header className="detail-head">
        <Cover src={album.cover_ready ? url.albumCover(album) : null} label={album.title} />
        <div className="detail-text">
          <span className="muted small">{tr("Album")}</span>
          <h1>{album.title}</h1>
          <p><Link to={`/listen/artist?name=${encodeURIComponent(album.artist)}`}>{album.artist}</Link>
            <span className="muted"> · {[album.year, album.genre, `${album.track_count} songs`, hours(album.duration)].filter(Boolean).join(" · ")}</span></p>
          <div className="admin-row"><PlayButtons tracks={album.tracks} /></div>
        </div>
      </header>
      <TrackList tracks={album.tracks} numbered showAlbum={false} />
      {discs && <p className="muted small">{tr("Songs from every disc, in disc order.")}</p>}
    </div>
  );
}

export function ArtistsPage() {
  const [artists, setArtists] = useState<Artist[] | null>(null);
  const [filter, setFilter] = useState("");
  useEffect(() => { api.artists().then(setArtists).catch(() => setArtists([])); }, []);
  const shown = artists?.filter((a) => !filter || a.name.toLowerCase().includes(filter.toLowerCase()));
  return (
    <Page title={tr("Artists")}>
      <div className="lib-tools">
        <label className="search"><Search size={17} aria-hidden />
          <input placeholder={tr("Search artists")} value={filter} onChange={(e) => setFilter(e.target.value)} aria-label={tr("Search artists")} /></label>
      </div>
      <div className="mtile-grid">
        {shown?.map((a) => (
          <Link key={a.name} to={`/listen/artist?name=${encodeURIComponent(a.name)}`} className="mtile">
            <Cover src={a.cover_album_id ? url.albumCover({ id: a.cover_album_id }) : null} label={a.name} round />
            <span className="poster-title">{a.name}</span>
            <span className="poster-meta">{a.album_count} {a.album_count === 1 ? "album" : "albums"}, {a.track_count}{" "}{tr("songs")}</span>
          </Link>
        ))}
      </div>
    </Page>
  );
}

export function ArtistDetailPage() {
  const [params] = useSearchParams();
  const name = params.get("name") ?? "";
  const [artist, setArtist] = useState<ArtistDetail | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.artist(name).then(setArtist).catch((e) => setError(e.message)); }, [name]);
  return (
    <div className="page cinema-page listen-page">
      <Link to="/listen/artists" className="back"><ArrowLeft size={18} />{" "}{tr("Artists")}</Link>
      {error && <p className="error">{error}</p>}
      {artist && <>
        <header className="detail-head">
          <Cover src={artist.albums.find((a) => a.cover_ready) ? url.albumCover(artist.albums.find((a) => a.cover_ready)!) : null} label={artist.name} round />
          <div className="detail-text">
            <span className="muted small">{tr("Artist")}</span>
            <h1>{artist.name}</h1>
            <p className="muted">{artist.albums.length} {artist.albums.length === 1 ? "album" : "albums"}, {artist.tracks.length}{" "}{tr("songs")}</p>
            <div className="admin-row"><PlayButtons tracks={artist.tracks} /></div>
          </div>
        </header>
        <h2 className="shelf-title">{tr("Songs")}</h2>
        <TrackList tracks={artist.tracks.slice(0, 10)} />
        <h2 className="shelf-title">{tr("Albums")}</h2>
        <div className="mtile-grid">{artist.albums.map((a) => <AlbumCard key={a.id} a={a} />)}</div>
      </>}
    </div>
  );
}

// ---------------------------------------------------------------- songs

export function SongsPage() {
  const [params, setParams] = useSearchParams();
  const favorites = params.get("favorites") === "1";
  const [tracks, setTracks] = useState<Track[] | null>(null);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<"title" | "artist" | "added">("title");
  useEffect(() => {
    const t = setTimeout(() => {
      api.songs({ q: query.trim() || undefined, favorites, sort, limit: 2000 }).then(setTracks).catch(() => setTracks([]));
    }, query ? 250 : 0);
    return () => clearTimeout(t);
  }, [query, favorites, sort]);
  return (
    <Page title={favorites ? tr("Favourites") : tr("Songs")}>
      <div className="lib-tools">
        <label className="search"><Search size={17} aria-hidden />
          <input placeholder={tr("Search songs, artists, albums")} value={query} onChange={(e) => setQuery(e.target.value)} aria-label={tr("Search songs")} /></label>
        <label className="check"><input type="checkbox" checked={favorites}
          onChange={(e) => setParams(e.target.checked ? { favorites: "1" } : {})} />{" "}{tr("Favourites only")}</label>
        <label className="sort">{tr("Sort by")}<select value={sort} onChange={(e) => setSort(e.target.value as typeof sort)}>
            <option value="title">{tr("Title")}</option><option value="artist">{tr("Artist")}</option><option value="added">{tr("Recently added")}</option>
          </select>
        </label>
        {tracks && tracks.length > 0 && <div className="admin-row"><PlayButtons tracks={tracks} /></div>}
      </div>
      {tracks?.length === 0 && <p className="muted">{favorites ? tr("Press the heart next to a song to add it here.") : query ? tr("Nothing matches \"{query}\".", { query: query }) : tr("No songs yet.")}</p>}
      {tracks && <TrackList tracks={tracks} />}
    </Page>
  );
}

// -------------------------------------------------------------- playlists

export function PlaylistsPage() {
  const [lists, setLists] = useState<Playlist[] | null>(null);
  const [name, setName] = useState("");
  const [favCount, setFavCount] = useState(0);
  const navigate = useNavigate();
  useEffect(() => {
    api.playlists().then(setLists).catch(() => setLists([]));
    api.musicHome().then((h) => setFavCount(h.favorite_count)).catch(() => undefined);
  }, []);
  const create = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    const p = await api.createPlaylist(name.trim());
    navigate(`/listen/playlist/${p.id}`);
  };
  return (
    <Page title={tr("Playlists")}>
      <form className="admin-row" onSubmit={create} style={{ marginBottom: 20 }}>
        <label>{tr("New playlist")}<input value={name} onChange={(e) => setName(e.target.value)} maxLength={128} placeholder={tr("Name")} /></label>
        <button className="primary" disabled={!name.trim()}><Plus size={16} />{" "}{tr("Create")}</button>
      </form>
      <div className="mtile-grid">
        <FavoritesTile count={favCount} />
        {lists?.map((p) => <PlaylistTile key={p.id} p={p} />)}
      </div>
      {lists?.length === 0 && <p className="muted">{tr("Make a playlist here, or use \"Add to playlist\" in the menu next to any song.")}</p>}
    </Page>
  );
}

export function PlaylistDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [p, setP] = useState<PlaylistDetail | null>(null);
  const [error, setError] = useState("");
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState("");
  useEffect(() => { if (id) api.playlist(id).then(setP).catch((e) => setError(e.message)); }, [id]);
  if (error) return <Page title={tr("Playlist")}><p className="error">{error}</p></Page>;
  if (!p) return <div className="page cinema-page" aria-busy="true" />;
  const save = async (ids: string[]) => setP(await api.updatePlaylist(p.id, { track_ids: ids }));
  const ids = p.tracks.map((t) => t.id);
  const move = (i: number, d: -1 | 1) => { const n = [...ids]; [n[i], n[i + d]] = [n[i + d], n[i]]; void save(n); };
  const removeAt = (i: number) => void save(ids.filter((_, j) => j !== i));
  const rename = async (e: FormEvent) => { e.preventDefault(); setP(await api.updatePlaylist(p.id, { name })); setRenaming(false); };
  const del = async () => { if (confirm(tr("Delete the playlist \"{name}\"? The songs stay in your library.", { name: p.name }))) { await api.deletePlaylist(p.id); navigate("/listen/playlists"); } };
  return (
    <div className="page cinema-page listen-page">
      <Link to="/listen/playlists" className="back"><ArrowLeft size={18} />{" "}{tr("Playlists")}</Link>
      <header className="detail-head">
        <PlaylistTileArt p={p} />
        <div className="detail-text">
          <span className="muted small">{tr("Playlist")}</span>
          {renaming ? (
            <form className="admin-row" onSubmit={rename}>
              <input value={name} onChange={(e) => setName(e.target.value)} maxLength={128} aria-label={tr("Playlist name")} autoFocus />
              <button className="primary">{tr("Save")}</button><button type="button" onClick={() => setRenaming(false)}>{tr("Cancel")}</button>
            </form>
          ) : <h1>{p.name}</h1>}
          <p className="muted">{p.track_count}{" "}{tr("songs ·")}{" "}{hours(p.duration)}</p>
          <div className="admin-row">
            <PlayButtons tracks={p.tracks} />
            <button onClick={() => { setName(p.name); setRenaming(true); }}>{tr("Rename")}</button>
            <button className="icon" onClick={() => void del()} aria-label={tr("Delete playlist")}><Trash2 size={17} /></button>
          </div>
        </div>
      </header>
      {p.tracks.length === 0 && <p className="muted">{tr("Empty for now. Use \"Add to playlist\" in the menu next to any song.")}</p>}
      <TrackList tracks={p.tracks} onRemove={removeAt} onMove={move} />
    </div>
  );
}

function PlaylistTileArt({ p }: { p: Playlist }) {
  return (
    <div className={`cover mosaic n${Math.min(4, p.cover_album_ids.length)}`}>
      {p.cover_album_ids.length ? p.cover_album_ids.slice(0, 4).map((id) => <img key={id} src={url.albumCover({ id })} alt="" />)
        : <span className="cover-blank"><Music size={48} /></span>}
    </div>
  );
}

// -------------------------------------------------------------- audiobooks

export function AudiobooksPage() {
  const [books, setBooks] = useState<Book[] | null>(null);
  const [filter, setFilter] = useState("");
  const [sort, setSort] = useState<"added" | "title" | "author">("added");
  useEffect(() => { api.books({ kind: "audiobook", sort }).then(setBooks).catch(() => setBooks([])); }, [sort]);
  const shown = books?.filter((b) => !filter || `${b.title} ${b.author ?? ""} ${b.narrator ?? ""}`.toLowerCase().includes(filter.toLowerCase()));
  return (
    <Page title={tr("Audiobooks")}>
      <div className="lib-tools">
        <label className="search"><Search size={17} aria-hidden />
          <input placeholder={tr("Search audiobooks")} value={filter} onChange={(e) => setFilter(e.target.value)} aria-label={tr("Search audiobooks")} /></label>
        <label className="sort">{tr("Sort by")}<select value={sort} onChange={(e) => setSort(e.target.value as typeof sort)}>
            <option value="added">{tr("Recently added")}</option><option value="title">{tr("Title")}</option><option value="author">{tr("Author")}</option>
          </select>
        </label>
      </div>
      {shown?.length === 0 && <p className="muted">{filter ? tr("Nothing matches \"{filter}\".", { filter: filter }) : tr("No audiobooks yet. Put them in a folder called Audiobooks: one file per book, or one folder per book.")}</p>}
      <div className="mtile-grid books">{shown?.map((b) => <BookCard key={b.id} b={b} to={`/listen/book/${b.id}`} />)}</div>
    </Page>
  );
}

export function AudiobookPage() {
  const { id } = useParams();
  const a = useAudio();
  const [b, setB] = useState<BookDetail | null>(null);
  const [error, setError] = useState("");
  const load = () => { if (id) api.book(id).then(setB).catch((e) => setError(e instanceof ApiError ? e.message : tr("Couldn't load this book"))); };
  useEffect(load, [id]);
  const here = a.book?.id === b?.id && a.current?.kind === "book";
  const pos = here ? a.bookTime : (b?.progress && !b.progress.finished ? b.progress.position : 0);
  const chapterAt = useMemo(() => {
    if (!b) return -1;
    let i = -1;
    b.chapters.forEach((c, j) => { if (c.start <= pos + 0.25) i = j; });
    return i;
  }, [b, pos]);
  if (error) return <Page title={tr("Audiobook")}><p className="error">{error}</p></Page>;
  if (!b) return <div className="page cinema-page" aria-busy="true" />;
  const startOver = async () => { await api.resetBookProgress(b.id); a.playBook({ ...b, progress: null }, 0); };
  return (
    <div className="page cinema-page listen-page">
      <Link to="/listen/audiobooks" className="back"><ArrowLeft size={18} />{" "}{tr("Audiobooks")}</Link>
      <header className="detail-head">
        <div className="cover tall">{b.cover_ready ? <img src={url.bookCover(b)} alt="" /> : <span className="cover-blank"><Headphones size={44} /></span>}</div>
        <div className="detail-text">
          <span className="muted small">{tr("Audiobook")}</span>
          <h1>{b.title}</h1>
          <p>{b.author && <>{tr("by")}{" "}{b.author}</>}{b.narrator && <span className="muted">{" "}{tr("· read by")}{" "}{b.narrator}</span>}</p>
          <p className="muted small">{[hours(b.duration ?? 0), b.year, b.chapters.length ? `${b.chapters.length} chapters` : null].filter(Boolean).join(" · ")}</p>
          {pos > 0 && b.duration && <div className="book-progress"><span style={{ width: `${Math.min(100, (pos / b.duration) * 100)}%` }} /></div>}
          <div className="admin-row">
            {here ? (
              <button className="primary" onClick={a.toggle}>{a.playing ? <Pause size={17} /> : <Play size={17} fill="currentColor" />}
                {a.playing ? tr("Pause") : tr("Play")}</button>
            ) : (
              <button className="primary" onClick={() => a.playBook(b)}><Play size={17} fill="currentColor" />
                {pos > 0 ? tr("Resume from {clock}", { clock: clock(pos) }) : tr("Play")}</button>
            )}
            {pos > 0 && <button onClick={() => void startOver()}><RotateCcw size={16} />{" "}{tr("Start over")}</button>}
            {b.downloadable && <a className="button" href={url.bookFile(b, true)}>{tr("Download")}</a>}
          </div>
          {b.description && <p className="overview">{b.description}</p>}
        </div>
      </header>
      {b.chapters.length > 0 && <>
        <h2 className="shelf-title">{tr("Chapters")}</h2>
        <ol className="tracks chapters">
          {b.chapters.map((c, i) => (
            <li key={i} className={i === chapterAt && pos > 0 ? "now" : ""}>
              <button className="track-main" onClick={() => a.playBook(b, c.start)}>
                <span className="track-no">{i + 1}</span>
                <span className="track-text"><span className="track-title">{c.title}</span></span>
                <span className="muted small track-dur">{clock(c.start)}</span>
              </button>
            </li>
          ))}
        </ol>
      </>}
    </div>
  );
}
