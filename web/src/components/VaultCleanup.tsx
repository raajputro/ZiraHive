// Vault clean-up: duplicate and blurry photos, or duplicate documents. Everything is compared
// here in the browser (the server can't read vault files). The vault has no trash, so removing
// deletes forever, after asking.
import { useEffect, useRef, useState } from "react";
import { Check, Trash2 } from "lucide-react";
import { api } from "../api";
import { locale, t as tr } from "../i18n";
import Dialog from "./Dialog";
import DuplicateDocs, { type DocGroup } from "./DuplicateDocs";
import { cleanUpDocuments, cleanUpPhotos, type DocCleanupGroup, type PhotoCleanup } from "../vault/compare";
import { folderOf } from "../vault/folders";
import type { Opened } from "../vault/files";

const num = (n: number) => n.toLocaleString(locale());

export default function VaultCleanup({ what, items, thumbs, onChanged, onClose }: {
  what: "photos" | "documents";
  items: Opened[];
  thumbs: Record<string, string>;
  onChanged: () => void;
  onClose: () => void;
}) {
  const [progress, setProgress] = useState<[number, number]>([0, 0]);
  const [photos, setPhotos] = useState<PhotoCleanup | null>(null);
  const [docs, setDocs] = useState<DocCleanupGroup[] | null>(null);
  const [gone, setGone] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const cancelled = useRef(false);

  useEffect(() => {
    cancelled.current = false;
    const onProgress = (done: number, total: number) => !cancelled.current && setProgress([done, total]);
    const run = what === "photos"
      ? cleanUpPhotos(items, thumbs, onProgress, () => cancelled.current).then((r) => !cancelled.current && setPhotos(r))
      : cleanUpDocuments(items, onProgress, () => cancelled.current).then((r) => !cancelled.current && setDocs(r));
    run.catch(() => setError(tr("Couldn't compare the files.")));
    return () => { cancelled.current = true; };
  }, [what]);  // items/thumbs: a snapshot is enough, the list is refreshed after deleting

  const byId = new Map(items.map((o) => [o.item.id, o]));
  const remove = async (ids: string[]) => {
    if (!ids.length) return;
    const ask = ids.length === 1
      ? tr("Delete \"{name}\" from the vault forever?", { name: byId.get(ids[0])?.meta.name ?? "" })
      : tr("Delete {count} items from the vault forever?", { count: ids.length });
    if (!confirm(ask)) return;
    setBusy(true); setError("");
    try {
      for (const id of ids) { await api.deleteVaultItem(id); setGone((g) => new Set([...g, id])); }
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); onChanged(); }
  };

  const working = what === "photos" ? !photos : !docs;
  const [done, total] = progress;
  return (
    <Dialog title={what === "photos" ? tr("Clean up vault photos") : tr("Duplicate documents in the vault")} onClose={onClose} wide>
      <div className="cleanup vault-cleanup">
        {error && <p className="error" role="alert">{error}</p>}
        {working ? (
          <div>
            <p className="muted">{what === "photos" ? tr("Comparing photos...") : tr("Comparing documents (each one is decrypted here, so this can take a while)...")}</p>
            <progress max={Math.max(1, total)} value={done} aria-label={tr("Comparing")} />
            {total > 0 && <p className="muted small">{num(done)} / {num(total)}</p>}
          </div>
        ) : what === "photos" ? <PhotoResults result={photos!} gone={gone} thumbs={thumbs} byId={byId} busy={busy} remove={remove} />
          : <DocResults groups={docs!} gone={gone} byId={byId} busy={busy} remove={remove} />}
      </div>
    </Dialog>
  );
}

function PhotoResults({ result, gone, thumbs, byId, busy, remove }: {
  result: PhotoCleanup; gone: Set<string>; thumbs: Record<string, string>; byId: Map<string, Opened>; busy: boolean; remove: (ids: string[]) => void;
}) {
  const groups = result.duplicates.map((g) => ({ ...g, ids: g.ids.filter((id) => !gone.has(id)) }))
    .filter((g) => g.ids.length > 1 && g.ids.includes(g.keep));
  const blurry = result.blurry.filter((id) => !gone.has(id));
  const extra = groups.flatMap((g) => g.ids.filter((id) => id !== g.keep));
  const pic = (id: string) => <img src={thumbs[id]} alt={byId.get(id)?.meta.name ?? ""} loading="lazy" />;
  return (
    <>
      <section>
        <h3>{tr("Duplicates")}</h3>
        <p className="muted small">{tr("Copies and near-copies of the same picture. The best one is marked Keep. Deleted photos are gone forever.")}</p>
        {groups.length === 0 ? <p className="muted"><Check size={16} aria-hidden />{" "}{tr("No duplicates.")}</p> : (
          <>
            <button className="primary" disabled={busy} onClick={() => remove(extra)}><Trash2 size={16} />{" "}{tr("Keep the best of each, delete {n} copies", { n: num(extra.length) })}</button>
            {groups.map((g) => (
              <div key={g.keep} className="dupe-group">
                {g.ids.map((id) => {
                  const m = byId.get(id)?.meta;
                  return (
                    <figure key={id} className={id === g.keep ? "keep" : ""}>
                      <div className="dupe-pic">{pic(id)}</div>
                      <figcaption className="small">
                        {id === g.keep ? <span className="tag">{tr("Keep")}</span>
                          : <button className="link-button" disabled={busy} onClick={() => remove([id])}>{tr("Delete")}</button>}
                        <span className="muted">{m?.width && m?.height ? `${m.width}×${m.height}` : ""}</span>
                      </figcaption>
                    </figure>
                  );
                })}
              </div>
            ))}
          </>
        )}
      </section>
      <section>
        <h3>{tr("Blurry photos")}</h3>
        {blurry.length === 0 ? <p className="muted"><Check size={16} aria-hidden />{" "}{tr("No blurry photos found.")}</p> : (
          <>
            <button disabled={busy} onClick={() => remove(blurry)}><Trash2 size={16} />{" "}{tr("Delete all {n}", { n: num(blurry.length) })}</button>
            <div className="dupe-group">
              {blurry.map((id) => (
                <figure key={id}>
                  <div className="dupe-pic">{pic(id)}</div>
                  <figcaption className="small"><button className="link-button" disabled={busy} onClick={() => remove([id])}>{tr("Delete")}</button></figcaption>
                </figure>
              ))}
            </div>
          </>
        )}
      </section>
    </>
  );
}

function DocResults({ groups, gone, byId, busy, remove }: {
  groups: DocCleanupGroup[]; gone: Set<string>; byId: Map<string, Opened>; busy: boolean; remove: (ids: string[]) => void;
}) {
  const shown: DocGroup[] = groups.map((g) => ({
    keep: g.keep, same: g.same, similarity: g.similarity,
    files: g.ids.filter((id) => !gone.has(id) && byId.has(id)).map((id) => {
      const o = byId.get(id)!;
      return { id, name: o.meta.name, folder: folderOf(o), size: o.meta.size, date: o.meta.modified ?? o.item.created_at };
    }),
  })).filter((g) => g.files.length > 1 && g.files.some((f) => f.id === g.keep));
  return (
    <section>
      <p className="muted small">{tr("Copies of the same document, and edited versions of it (most of the words the same). PDFs and text files are compared by their words; other files only as exact copies. The newest is marked Keep. Deleted files are gone forever.")}</p>
      {shown.length === 0 ? <p className="muted"><Check size={16} aria-hidden />{" "}{tr("No duplicate documents.")}</p> : (
        <DuplicateDocs groups={shown} busy={busy} onRemove={remove}
          removeAllLabel={(n) => tr("Keep the newest of each, delete {n}", { n: num(n) })} />
      )}
    </section>
  );
}
