import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Link2, Plus, Trash2, Users, CheckSquare, Pencil } from "lucide-react";
import { api, ApiError, url, type Album, type AlbumDetail, type User } from "../api";
import { useAuth } from "../App";
import Dialog from "../components/Dialog";
import ShareDialog from "../components/ShareDialog";
import { Lightbox, PhotoTabs, Tile } from "./Photos";

import { t as tr } from "../i18n";
export default function AlbumsPage() {
  const [albums, setAlbums] = useState<Album[] | null>(null);
  const [creating, setCreating] = useState(false);
  const navigate = useNavigate();
  useEffect(() => { api.albums().then(setAlbums).catch(() => setAlbums([])); }, []);

  return (
    <div className="page">
      <header className="page-head">
        <h1>{tr("Photos")}</h1>
        <button className="primary" onClick={() => setCreating(true)}><Plus size={17} />{" "}{tr("New album")}</button>
      </header>
      <PhotoTabs />
      {albums && albums.length === 0 && (
        <div className="empty">
          <h2>{tr("No albums yet")}</h2>
          <p>{tr("Make an album for a trip or an Eid, then share it with family. They can add their own photos too.")}</p>
        </div>
      )}
      <div className="album-grid">
        {albums?.map((a) => (
          <Link key={a.id} to={`/photos/albums/${a.id}`} className="album-card">
            <div className="album-cover">{a.cover_asset_id ? <img src={url.thumb({ id: a.cover_asset_id })} alt="" loading="lazy" /> : null}</div>
            <strong>{a.title}</strong>
            <span className="muted small">
              {a.item_count} {a.item_count === 1 ? "item" : "items"}
              {a.is_owner ? (a.members.length ? tr(", shared with {length}", { length: a.members.length }) : "") : tr(", from {owner}", { owner: a.owner })}
            </span>
          </Link>
        ))}
      </div>
      {creating && <NewAlbumDialog onClose={() => setCreating(false)} onCreated={(a) => navigate(`/photos/albums/${a.id}`)} />}
    </div>
  );
}

function NewAlbumDialog({ onClose, onCreated, assetIds = [] }:
  { onClose: () => void; onCreated: (a: Album) => void; assetIds?: string[] }) {
  const [title, setTitle] = useState("");
  const [error, setError] = useState("");
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try { onCreated(await api.createAlbum(title.trim(), assetIds)); }
    catch (err) { setError(err instanceof ApiError ? err.message : tr("Couldn't create the album")); }
  };
  return (
    <Dialog title={tr("New album")} onClose={onClose}>
      <form className="stack-form" onSubmit={submit}>
        <label>{tr("Name")}<input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={tr("Cox's Bazar 2026")} required autoFocus /></label>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="primary">{tr("Create album")}</button>
      </form>
    </Dialog>
  );
}

/** Pick an album (or make one) for the photos selected in the timeline. */
export function AddToAlbumDialog({ assetIds, onClose, onDone }:
  { assetIds: string[]; onClose: () => void; onDone: () => void }) {
  const [albums, setAlbums] = useState<Album[]>([]);
  const [making, setMaking] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { api.albums().then((all) => setAlbums(all.filter((a) => a.can_add))).catch(() => undefined); }, []);
  const add = async (a: Album) => {
    try { await api.addToAlbum(a.id, assetIds); onDone(); }
    catch (err) { setError(err instanceof ApiError ? err.message : tr("Couldn't add to the album")); }
  };
  if (making) return <NewAlbumDialog assetIds={assetIds} onClose={onClose} onCreated={() => onDone()} />;
  return (
    <Dialog title={tr("Add {length} to an album", { length: assetIds.length })} onClose={onClose}>
      <ul className="pick-list">
        <li><button onClick={() => setMaking(true)}><Plus size={16} />{" "}{tr("New album")}</button></li>
        {albums.map((a) => (
          <li key={a.id}><button onClick={() => void add(a)}>{a.title}<span className="muted small">{a.item_count}{" "}{tr("items")}</span></button></li>
        ))}
      </ul>
      {error && <p className="error" role="alert">{error}</p>}
    </Dialog>
  );
}

function MembersDialog({ album, onClose, onSaved }: { album: Album; onClose: () => void; onSaved: (a: Album) => void }) {
  const { user: me } = useAuth();
  const [people, setPeople] = useState<User[]>([]);
  const [chosen, setChosen] = useState<Record<string, { on: boolean; can_add: boolean }>>(() =>
    Object.fromEntries(album.members.map((m) => [m.user_id, { on: true, can_add: m.can_add }])));
  useEffect(() => { api.directory().then((all) => setPeople(all.filter((p) => p.id !== me.id))).catch(() => undefined); }, [me.id]);
  const save = async () => {
    const members = Object.entries(chosen).filter(([, v]) => v.on).map(([user_id, v]) => ({ user_id, can_add: v.can_add }));
    onSaved(await api.setAlbumMembers(album.id, members));
  };
  const set = (id: string, change: Partial<{ on: boolean; can_add: boolean }>) =>
    setChosen((c) => ({ ...c, [id]: { on: c[id]?.on ?? false, can_add: c[id]?.can_add ?? true, ...change } }));
  return (
    <Dialog title={tr("Share {title} with family", { title: album.title })} onClose={onClose}>
      {people.length === 0 && <p className="muted">{tr("Nobody else has an account yet. Add family members in Settings.")}</p>}
      <ul className="rows">
        {people.map((p) => (
          <li key={p.id}>
            <label className="check grow"><input type="checkbox" checked={chosen[p.id]?.on ?? false} onChange={(e) => set(p.id, { on: e.target.checked })} /> {p.username}</label>
            {chosen[p.id]?.on && (
              <label className="check small"><input type="checkbox" checked={chosen[p.id]?.can_add ?? true}
                onChange={(e) => set(p.id, { can_add: e.target.checked })} />{" "}{tr("can add photos")}</label>
            )}
          </li>
        ))}
      </ul>
      <button className="primary" onClick={() => void save()}>{tr("Save")}</button>
    </Dialog>
  );
}

export function AlbumPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [album, setAlbum] = useState<AlbumDetail | null>(null);
  const [error, setError] = useState("");
  const [viewer, setViewer] = useState<number | null>(null);
  const [dialog, setDialog] = useState<"members" | "link" | null>(null);
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const load = useCallback(() => { if (id) api.album(id).then(setAlbum).catch((e) => setError(e.message)); }, [id]);
  useEffect(load, [load]);

  if (error) return <div className="page"><p className="error">{error}</p></div>;
  if (!album) return <div className="page" aria-busy="true" />;

  const rename = async () => {
    const t = prompt(tr("Album name"), album.title);
    if (t?.trim()) { await api.updateAlbum(album.id, { title: t.trim() }); load(); }
  };
  const remove = async () => {
    if (!confirm(tr("Delete the album \"{title}\"? The photos stay in everyone's library.", { title: album.title }))) return;
    await api.deleteAlbum(album.id);
    navigate("/photos/albums");
  };
  const removeSelected = async () => {
    await api.removeFromAlbum(album.id, [...selected]);
    setSelecting(false); setSelected(new Set()); load();
  };
  const toggle = (aid: string) => setSelected((s) => { const n = new Set(s); if (n.has(aid)) n.delete(aid); else n.add(aid); return n; });

  return (
    <div className="page">
      <Link to="/photos/albums" className="back"><ArrowLeft size={18} />{" "}{tr("Albums")}</Link>
      <header className="page-head">
        <h1>{album.title}</h1>
        {selecting ? (
          <>
            <span className="muted">{selected.size}{" "}{tr("selected")}</span>
            <button className="danger" disabled={!selected.size} onClick={() => void removeSelected()}>{tr("Remove from album")}</button>
            <button onClick={() => { setSelecting(false); setSelected(new Set()); }}>{tr("Done")}</button>
          </>
        ) : (
          <>
            {album.items.length > 0 && <button onClick={() => setSelecting(true)}><CheckSquare size={17} />{" "}{tr("Select")}</button>}
            {album.is_owner && <button onClick={() => setDialog("members")}><Users size={17} />{" "}{tr("Share with family")}</button>}
            {album.is_owner && <button onClick={() => setDialog("link")}><Link2 size={17} />{" "}{tr("Link")}</button>}
            {album.is_owner && <button className="icon" onClick={() => void rename()} aria-label={tr("Rename album")} title={tr("Rename")}><Pencil size={17} /></button>}
            {album.is_owner && <button className="icon" onClick={() => void remove()} aria-label={tr("Delete album")} title={tr("Delete album")}><Trash2 size={17} /></button>}
          </>
        )}
      </header>
      <p className="muted album-meta">
        {album.is_owner ? tr("Your album") : tr("Shared by {owner}", { owner: album.owner })}
        {album.members.length > 0 && tr(", with {join}", { join: album.members.map((m) => m.username).join(", ") })}
        {album.can_add && ". To add photos, go to Timeline and press Select."}
      </p>
      {album.items.length === 0 && <div className="empty"><h2>{tr("This album is empty")}</h2><p>{tr("Go to Timeline, press Select, pick photos and choose Add to album.")}</p></div>}
      <div className="justified">
        {album.items.map((a, i) => (
          <Tile key={a.id} a={a} thumbUrl={url.thumb(a)} selecting={selecting} selected={selected.has(a.id)}
            onToggle={() => toggle(a.id)} onOpen={() => setViewer(i)} />
        ))}
        <span className="justified-filler" />
      </div>
      {viewer !== null && <Lightbox items={album.items} index={viewer} onIndex={setViewer} onClose={() => setViewer(null)} />}
      {dialog === "members" && <MembersDialog album={album} onClose={() => setDialog(null)} onSaved={() => { setDialog(null); load(); }} />}
      {dialog === "link" && <ShareDialog type="album" id={album.id} label={album.title} onClose={() => setDialog(null)} />}
    </div>
  );
}
