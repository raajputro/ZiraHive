// Dialogs for vault folders: naming one, and choosing where to move things.
import { useState, type FormEvent } from "react";
import { Folder, FolderPlus, ShieldCheck } from "lucide-react";
import Dialog from "./Dialog";
import { t as tr } from "../i18n";
import type { Opened } from "../vault/files";
import { allFolders, badName, createFolder, join, nameOf, ROOT } from "../vault/folders";

export function folderError(code: string): string {
  return code === "empty" ? tr("Type a name.")
    : code === "slash" ? tr("A folder name can't contain /.")
    : code === "long" ? tr("That name is too long.")
    : code === "taken" ? tr("There's already a folder with that name here.")
    : "";
}

/** Asks for a folder name. `current` (a path) means renaming that folder. */
export function FolderNameDialog({ items, parent, current, onSave, onClose }: {
  items: Opened[]; parent: string; current?: string; onSave: (name: string) => Promise<void>; onClose: () => void;
}) {
  const [name, setName] = useState(current ? nameOf(current) : "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const bad = badName(items, parent, name, current);
    if (bad) { setError(folderError(bad)); return; }
    setBusy(true);
    try { await onSave(name.trim()); onClose(); }
    catch (err) { setError(err instanceof Error ? err.message : tr("Couldn't save")); }
    finally { setBusy(false); }
  };
  return (
    <Dialog title={current ? tr("Rename folder") : tr("New folder")} onClose={onClose}>
      <form className="stack-form" onSubmit={submit}>
        <label>{tr("Folder name")}<input value={name} onChange={(e) => { setName(e.target.value); setError(""); }} autoFocus maxLength={120} /></label>
        <p className="muted small"><ShieldCheck size={13} aria-hidden /> {tr("Folder names are encrypted too.")}</p>
        {error && <p className="error" role="alert">{error}</p>}
        <div className="admin-row">
          <button className="primary" disabled={busy}>{busy ? tr("Saving…") : current ? tr("Rename") : tr("Create")}</button>
          <button type="button" onClick={onClose}>{tr("Cancel")}</button>
        </div>
      </form>
    </Dialog>
  );
}

/** Pick a destination folder. Can make a new folder on the way. */
export function MoveToFolderDialog({ master, items, count, from, onMove, onClose }: {
  master: CryptoKey; items: Opened[]; count: number; from?: string; onMove: (folder: string) => Promise<void>; onClose: () => void;
}) {
  const [extra, setExtra] = useState<string[]>([]);  // made in this dialog
  const [choice, setChoice] = useState<string>(from ?? ROOT);
  const [making, setMaking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const folders = [ROOT, ...new Set([...allFolders(items), ...extra])].sort((a, b) => (a === ROOT ? -1 : b === ROOT ? 1 : a.localeCompare(b)));
  const depth = (p: string) => (p === ROOT ? 0 : p.split("/").length - 1);
  const go = async () => {
    setBusy(true);
    try { await onMove(choice); onClose(); }
    catch (e) { setError(e instanceof Error ? e.message : tr("Couldn't move")); setBusy(false); }
  };
  if (making) {
    return (
      <FolderNameDialog items={items} parent={choice} onClose={() => setMaking(false)}
        onSave={async (name) => { await createFolder(master, choice, name); const p = join(choice, name); setExtra((x) => [...x, p]); setChoice(p); }} />
    );
  }
  return (
    <Dialog title={count === 1 ? tr("Move 1 item to…") : tr("Move {count} items to…", { count })} onClose={onClose}>
      <ul className="folder-pick" role="listbox" aria-label={tr("Folders")}>
        {folders.map((p) => (
          <li key={p}>
            <button role="option" aria-selected={choice === p} className={choice === p ? "on" : ""} style={{ paddingLeft: 10 + depth(p) * 18 }}
              onClick={() => setChoice(p)}>
              {p === ROOT ? <ShieldCheck size={16} aria-hidden /> : <Folder size={16} aria-hidden />}
              <span>{p === ROOT ? tr("Vault (top level)") : nameOf(p)}</span>
              {p === from && <small className="muted">{tr("here now")}</small>}
            </button>
          </li>
        ))}
      </ul>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="admin-row">
        <button className="primary" disabled={busy || choice === from} onClick={() => void go()}>{busy ? tr("Moving…") : tr("Move here")}</button>
        <button onClick={() => setMaking(true)}><FolderPlus size={16} /> {tr("New folder in {name}", { name: choice === ROOT ? tr("Vault") : nameOf(choice) })}</button>
        <button onClick={onClose}>{tr("Cancel")}</button>
      </div>
      <p className="muted small">{tr("Moving only changes encrypted details; the files stay as they are.")}</p>
    </Dialog>
  );
}

