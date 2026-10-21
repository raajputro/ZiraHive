// Vault folders. A folder is an empty encrypted item of type FOLDER_TYPE whose (encrypted) meta
// holds its name and parent; every file's encrypted meta says which folder it is in. Folder
// names and the layout are therefore as private as the files: the server only sees items.
import { api } from "../api";
import { sealMeta } from "./crypto";
import { encryptAndUpload, FOLDER_TYPE, type Opened } from "./files";

export const ROOT = "/";
export const isFolder = (o: Opened) => o.meta.type === FOLDER_TYPE;
export const folderOf = (o: Opened) => o.meta.folder || ROOT;
export const join = (parent: string, name: string) => (parent === ROOT ? "" : parent) + "/" + name;
export const pathOf = (folder: Opened) => join(folderOf(folder), folder.meta.name);
export const nameOf = (path: string) => path.split("/").pop() || "";
export const parentOf = (path: string) => path.slice(0, path.lastIndexOf("/")) || ROOT;
/** `path` itself or anything below it. */
export const within = (folder: string, path: string) => folder === path || folder.startsWith(path + "/");

/** Every folder path, including ones only implied by a file's location. Sorted. */
export function allFolders(items: Opened[]): string[] {
  const set = new Set<string>();
  const addWithParents = (p: string) => { for (let x = p; x !== ROOT; x = parentOf(x)) set.add(x); };
  for (const o of items) {
    if (isFolder(o)) addWithParents(pathOf(o));
    else if (folderOf(o) !== ROOT) addWithParents(folderOf(o));
  }
  return [...set].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base", numeric: true }));
}
export const subfolders = (items: Opened[], path: string) => allFolders(items).filter((p) => parentOf(p) === path);
export const filesIn = (items: Opened[], path: string) => items.filter((o) => !isFolder(o) && folderOf(o) === path);
export const filesWithin = (items: Opened[], path: string) => items.filter((o) => !isFolder(o) && within(folderOf(o), path));

/** Why a folder name can't be used, or "" if it can. */
export function badName(items: Opened[], parent: string, name: string, current?: string): string {
  const n = name.trim();
  if (!n) return "empty";
  if (n.includes("/") || n === "." || n === "..") return "slash";
  if (n.length > 120) return "long";
  const taken = subfolders(items, parent).some((p) => p !== current && nameOf(p).toLocaleLowerCase() === n.toLocaleLowerCase());
  return taken ? "taken" : "";
}

export async function createFolder(master: CryptoKey, parent: string, name: string): Promise<void> {
  await encryptAndUpload(master, new File([], name.trim(), { type: FOLDER_TYPE }), { folder: parent });
}

/** Re-seal one item's meta with a change (the file itself isn't touched). */
async function reseal(o: Opened, change: Partial<Opened["meta"]>) {
  const meta = { ...o.meta, ...change };
  if (!meta.folder || meta.folder === ROOT) delete meta.folder;
  await api.renameVaultItem(o.item.id, await sealMeta(o.fk, meta));
}

export async function moveTo(o: Opened, folder: string) { await reseal(o, { folder }); }

/** Rename `path`: its marker and everything below it get the new location. */
export async function renameFolder(master: CryptoKey, items: Opened[], path: string, name: string) {
  const to = join(parentOf(path), name.trim());
  const marker = items.find((o) => isFolder(o) && pathOf(o) === path);
  if (marker) await reseal(marker, { name: name.trim() });
  else await createFolder(master, parentOf(path), name);  // it only existed through its files
  for (const o of items) {
    if (o === marker) continue;
    const f = folderOf(o);
    if (within(f, path)) await reseal(o, { folder: to + f.slice(path.length) });
  }
}

/** Delete `path` and everything in it, forever. */
export async function deleteFolder(items: Opened[], path: string) {
  for (const o of items) {
    if ((isFolder(o) && within(pathOf(o), path)) || (!isFolder(o) && within(folderOf(o), path))) await api.deleteVaultItem(o.item.id);
  }
}
