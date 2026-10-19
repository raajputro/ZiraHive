// Photo search by description, People and Clean up.
import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ArrowLeft, Check, EyeOff, Merge, Pencil, Search, Sparkles, Trash2, UserX } from "lucide-react";
import { api, ApiError, url, type Asset, type Cleanup, type PersonSummary } from "../api";
import { Lightbox, PhotoTabs, Tile } from "./Photos";
import { num, t as tr } from "../i18n";

/** The search box in the Photos tabs. */
export function PhotoSearchBox() {
  const [params] = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const navigate = useNavigate();
  return (
    <form className="search photo-search" role="search" onSubmit={(e) => { e.preventDefault(); if (q.trim()) navigate(`/photos/search?q=${encodeURIComponent(q.trim())}`); }}>
      <Search size={16} aria-hidden />
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={tr("Search: beach, birthday cake, red car…")} aria-label={tr("Search photos by what's in them")} />
    </form>
  );
}

function AiOff({ message }: { message: string }) {
  return (
    <div className="empty">
      <h2><Sparkles size={20} aria-hidden />{" "}{tr("Needs the local AI")}</h2>
      <p>{message}</p>
    </div>
  );
}

function Grid({ items }: { items: Asset[] }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <>
      <div className="justified">
        {items.map((a, i) => <Tile key={a.id} a={a} thumbUrl={url.thumb(a)} onOpen={() => setOpen(i)} />)}
        <span className="justified-filler" />
      </div>
      {open !== null && items[open] && <Lightbox items={items} index={open} onIndex={setOpen} onClose={() => setOpen(null)} />}
    </>
  );
}

// Recent searches, so going back to one shows its photos at once (they are refreshed quietly).
const recentSearches = new Map<string, { hits: Asset[]; english: string }>();

export function PhotoSearchPage() {
  const [params] = useSearchParams();
  const q = params.get("q") ?? "";
  const [hits, setHits] = useState<Asset[] | null>(() => recentSearches.get(q)?.hits ?? null);
  const [english, setEnglish] = useState(() => recentSearches.get(q)?.english ?? "");
  const [off, setOff] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    if (!q) return;
    let current = true;
    const seen = recentSearches.get(q);
    setHits(seen?.hits ?? null); setEnglish(seen?.english ?? ""); setOff(""); setError("");
    api.searchPhotos(q).then((r) => {
      const found = { hits: r.hits.map((h) => h.asset), english: r.searched_for !== r.query ? r.searched_for : "" };
      recentSearches.delete(q); recentSearches.set(q, found);
      if (recentSearches.size > 30) recentSearches.delete(recentSearches.keys().next().value!);
      if (current) { setHits(found.hits); setEnglish(found.english); }
    }).catch((e) => { if (!current) return; if (e instanceof ApiError && e.code === "ai_off") setOff(e.message); else setError(e.message); });
    return () => { current = false; };
  }, [q]);
  return (
    <div className="page">
      <header className="page-head"><h1>{tr("Photos")}</h1></header>
      <PhotoTabs />
      <h2 className="shelf-title">{tr("Photos of \"{q}\"", { q })}</h2>
      {english && <p className="muted small">{tr("Searched for: {words}", { words: english })}</p>}
      {off && <AiOff message={off} />}
      {error && <p className="error">{error}</p>}
      {!hits && !off && !error && <p className="muted" aria-busy="true">{tr("Looking…")}</p>}
      {hits && hits.length === 0 && <p className="muted">{tr("No photos look like that. Try other words, in English or Bangla.")}</p>}
      {hits && <Grid items={hits} />}
    </div>
  );
}

export function PeoplePage() {
  const [people, setPeople] = useState<PersonSummary[] | null>(null);
  const [off, setOff] = useState(false);
  useEffect(() => {
    api.people().then(setPeople).catch(() => setPeople([]));
    api.aiStatus().then((s) => setOff(!s.ai)).catch(() => undefined);
  }, []);
  return (
    <div className="page">
      <header className="page-head"><h1>{tr("Photos")}</h1></header>
      <PhotoTabs />
      {people && people.length === 0 && (off
        ? <AiOff message={tr("Faces are found by the local AI. An admin can turn it on; see docs/AI.md.")} />
        : <div className="empty"><h2>{tr("No people yet")}</h2><p>{tr("Faces are grouped as photos are looked at, in the background. A person shows up once they're in two photos.")}</p></div>)}
      <ul className="people-grid">
        {people?.map((p) => (
          <li key={p.id}>
            <Link to={`/photos/people/${p.id}`}>
              {p.cover_face ? <img src={url.face(p.cover_face)} alt="" loading="lazy" /> : <span className="face-blank" />}
              <strong>{p.name ?? tr("Add a name")}</strong>
              <span className="muted small">{tr("{n} photos", { n: num(p.photos) })}</span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function PersonPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [person, setPerson] = useState<PersonSummary | null>(null);
  const [photos, setPhotos] = useState<Asset[]>([]);
  const [faces, setFaces] = useState<{ id: string; asset_id: string }[]>([]);
  const [others, setOthers] = useState<PersonSummary[]>([]);
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  const [fixing, setFixing] = useState(false);
  const load = () => {
    api.people().then((all) => { setPerson(all.find((p) => p.id === id) ?? null); setOthers(all.filter((p) => p.id !== id)); }).catch(() => undefined);
    api.personPhotos(id).then(setPhotos).catch(() => undefined);
    api.personFaces(id).then(setFaces).catch(() => undefined);
  };
  useEffect(load, [id]);
  const save = async (e: FormEvent) => { e.preventDefault(); const p = await api.updatePerson(id, { name }); setPerson(p); setNaming(false); };
  const merge = async (into: string) => { await api.mergePeople(id, into); navigate(`/photos/people/${into}`, { replace: true }); };
  const hide = async () => { await api.updatePerson(id, { hidden: true }); navigate("/photos/people"); };
  return (
    <div className="page">
      <Link to="/photos/people" className="back"><ArrowLeft size={18} />{" "}{tr("People")}</Link>
      <header className="page-head person-head">
        {person?.cover_face && <img className="face-big" src={url.face(person.cover_face)} alt="" />}
        {naming ? (
          <form className="inline-form" onSubmit={save}>
            <label>{tr("Name")}<input value={name} onChange={(e) => setName(e.target.value)} autoFocus maxLength={100} /></label>
            <button className="primary">{tr("Save")}</button>
          </form>
        ) : (
          <>
            <h1>{person?.name ?? tr("Who is this?")}</h1>
            <button onClick={() => { setName(person?.name ?? ""); setNaming(true); }}><Pencil size={16} />{" "}{person?.name ? tr("Rename") : tr("Add a name")}</button>
          </>
        )}
      </header>
      <div className="admin-row">
        <button onClick={() => setFixing((f) => !f)} aria-pressed={fixing}><UserX size={16} />{" "}{fixing ? tr("Done") : tr("Remove wrong photos")}</button>
        {others.length > 0 && (
          <label className="inline-select"><Merge size={16} aria-hidden />{" "}{tr("Same person as")}
            <select value="" onChange={(e) => e.target.value && void merge(e.target.value)}>
              <option value="">{tr("Choose…")}</option>
              {others.map((o) => <option key={o.id} value={o.id}>{o.name ?? tr("Unnamed, {n} photos", { n: o.photos })}</option>)}
            </select>
          </label>
        )}
        <button onClick={() => void hide()}><EyeOff size={16} />{" "}{tr("Hide this person")}</button>
      </div>
      {fixing ? (
        <ul className="face-fix">
          {faces.map((f) => (
            <li key={f.id}>
              <img src={url.face(f.id)} alt="" loading="lazy" />
              <button className="icon" aria-label={tr("Not this person")} onClick={async () => { await api.notThisPerson(id, f.id); load(); }}><UserX size={16} /></button>
            </li>
          ))}
        </ul>
      ) : <Grid items={photos} />}
    </div>
  );
}

export function CleanupPage() {
  const [data, setData] = useState<Cleanup | null>(null);
  const [gone, setGone] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<{ items: Asset[]; i: number } | null>(null);
  useEffect(() => { api.cleanup().then(setData).catch(() => undefined); }, []);
  const trash = async (ids: string[]) => {
    setBusy(true);
    try { for (const id of ids) await api.trashAsset(id); setGone((g) => new Set([...g, ...ids])); } finally { setBusy(false); }
  };
  if (!data) return <div className="page" aria-busy="true"><PhotoTabs /></div>;
  const groups = data.duplicates.map((g) => ({ ...g, photos: g.photos.filter((p) => !gone.has(p.id)) })).filter((g) => g.photos.length > 1);
  const blurry = data.blurry.filter((p) => !gone.has(p.id));
  const extra = groups.flatMap((g) => g.photos.filter((p) => p.id !== g.keep).map((p) => p.id));
  return (
    <div className="page cleanup">
      <header className="page-head"><h1>{tr("Photos")}</h1></header>
      <PhotoTabs />
      {data.waiting > 0 && <p className="notice small">{tr("{n} photos are still being looked at. Come back later for them.", { n: num(data.waiting) })}</p>}
      <section>
        <h2>{tr("Duplicates")}</h2>
        <p className="muted small">{tr("Copies and near-copies of the same picture. The best one is marked Keep. Removed photos go to the trash for 30 days.")}</p>
        {groups.length === 0 ? <p className="muted"><Check size={16} aria-hidden />{" "}{tr("No duplicates.")}</p> : (
          <>
            <button className="primary" disabled={busy} onClick={() => void trash(extra)}><Trash2 size={16} />{" "}{tr("Keep the best of each, remove {n} copies", { n: num(extra.length) })}</button>
            {groups.map((g) => (
              <div key={g.keep} className="dupe-group">
                {g.photos.map((p, i) => (
                  <figure key={p.id} className={p.id === g.keep ? "keep" : ""}>
                    <button className="dupe-pic" onClick={() => setOpen({ items: g.photos, i })} aria-label={tr("Open")+" "+p.filename}><img src={url.thumb(p)} alt="" loading="lazy" /></button>
                    <figcaption className="small">
                      {p.id === g.keep ? <span className="tag">{tr("Keep")}</span>
                        : <button className="link-button" disabled={busy} onClick={() => void trash([p.id])}>{tr("Remove")}</button>}
                      <span className="muted">{p.width && p.height ? `${p.width}×${p.height}` : ""}</span>
                    </figcaption>
                  </figure>
                ))}
              </div>
            ))}
          </>
        )}
      </section>
      <section>
        <h2>{tr("Blurry photos")}</h2>
        {blurry.length === 0 ? <p className="muted"><Check size={16} aria-hidden />{" "}{tr("No blurry photos found.")}</p> : (
          <>
            <button disabled={busy} onClick={() => void trash(blurry.map((p) => p.id))}><Trash2 size={16} />{" "}{tr("Remove all {n}", { n: num(blurry.length) })}</button>
            <div className="dupe-group">
              {blurry.map((p, i) => (
                <figure key={p.id}>
                  <button className="dupe-pic" onClick={() => setOpen({ items: blurry, i })} aria-label={tr("Open")+" "+p.filename}><img src={url.thumb(p)} alt="" loading="lazy" /></button>
                  <figcaption className="small"><button className="link-button" disabled={busy} onClick={() => void trash([p.id])}>{tr("Remove")}</button></figcaption>
                </figure>
              ))}
            </div>
          </>
        )}
      </section>
      {open && <Lightbox items={open.items} index={open.i} onIndex={(i) => setOpen({ ...open, i })} onClose={() => setOpen(null)} />}
    </div>
  );
}
