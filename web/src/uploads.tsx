import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import { X, Check, AlertCircle, Copy } from "lucide-react";
import { api, ApiError, formatBytes } from "./api";

const CHUNK = 8 * 1024 * 1024;
const HASH_LIMIT = 512 * 1024 * 1024; // hash in the browser below this size; the server always verifies

type State = "queued" | "hashing" | "uploading" | "done" | "exists" | "error";
interface Item { key: string; file: File; folder: string; dedupe: boolean; sent: number; state: State; error?: string }

interface Ctx { enqueue: (files: File[], folder: string, opts?: { dedupe?: boolean }) => void; onComplete: (fn: () => void) => () => void }
const UploadContext = createContext<Ctx | null>(null);
export const useUploads = () => useContext(UploadContext)!;

async function sha256(file: File): Promise<string | undefined> {
  // crypto.subtle only exists on https:// or localhost; on plain LAN http the server hashes instead.
  if (!window.crypto?.subtle || file.size > HASH_LIMIT) return undefined;
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function UploadProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Item[]>([]);
  const queue = useRef<Item[]>([]);
  const running = useRef(false);
  const listeners = useRef(new Set<() => void>());

  const patch = (key: string, change: Partial<Item>) =>
    setItems((list) => list.map((i) => (i.key === key ? { ...i, ...change } : i)));

  const uploadOne = async (item: Item) => {
    patch(item.key, { state: "hashing" });
    const hash = await sha256(item.file);
    patch(item.key, { state: "uploading" });
    let res = await api.uploadCreate({
      filename: item.file.name, size: item.file.size, folder: item.folder, sha256: hash, dedupe: item.dedupe,
      taken_at: item.file.type.startsWith("image/") || item.file.type.startsWith("video/")
        ? new Date(item.file.lastModified).toISOString() : undefined,
    });
    let offset = res.offset;
    while (res.status === "uploading" && res.id) {
      try {
        res = await api.uploadChunk(res.id, offset, item.file.slice(offset, offset + CHUNK));
      } catch (e) {
        // Dropped connection or offset mismatch: ask the server where it got to, then continue.
        if (e instanceof ApiError && e.status !== 409 && e.status < 500) throw e;
        await new Promise((r) => setTimeout(r, 1500));
        res = await api.uploadStatus(res.id!);
      }
      offset = res.offset;
      patch(item.key, { sent: offset });
    }
    patch(item.key, { state: res.status === "exists" ? "exists" : "done", sent: item.file.size });
    return res.status === "exists" ? "exists" : "done";
  };

  const pump = useCallback(async () => {
    if (running.current) return;
    running.current = true;
    // photo-backup style uploads (dedupe on) are reported so they show as a notification
    const run = { uploaded: 0, skipped: 0, failed: 0, backup: false };
    while (queue.current.length) {
      const item = queue.current.shift()!;
      run.backup ||= item.dedupe;
      try { if ((await uploadOne(item)) === "exists") run.skipped++; else run.uploaded++; }
      catch (e) { run.failed++; patch(item.key, { state: "error", error: e instanceof Error ? e.message : "Upload failed" }); }
      listeners.current.forEach((fn) => fn());
    }
    // Report bigger backups, and any failure, so a push notification reaches the phone
    // (the browser itself can't wake a locked screen).
    if (run.failed > 0 || (run.backup && run.uploaded + run.skipped >= 5)) {
      const device = /iPhone|iPad/.test(navigator.userAgent) ? "iPhone" : /Android/.test(navigator.userAgent) ? "Android phone" : "browser";
      void api.reportBackup({ ...run, device }).catch(() => undefined);
    }
    running.current = false;
  }, []);

  const enqueue = useCallback((files: File[], folder: string, opts: { dedupe?: boolean } = {}) => {
    const added = files.map((file) => ({ key: `${Date.now()}-${Math.random()}`, file, folder, dedupe: opts.dedupe ?? true,
      sent: 0, state: "queued" as State }));
    queue.current.push(...added);
    setItems((list) => [...list, ...added]);
    void pump();
  }, [pump]);

  const onComplete = useCallback((fn: () => void) => {
    listeners.current.add(fn);
    return () => { listeners.current.delete(fn); };
  }, []);

  const active = items.filter((i) => !["done", "exists", "error"].includes(i.state)).length;
  const total = items.reduce((s, i) => s + i.file.size, 0);
  const sent = items.reduce((s, i) => s + i.sent, 0);

  return (
    <UploadContext.Provider value={{ enqueue, onComplete }}>
      {children}
      {items.length > 0 && (
        <aside className="tray" aria-live="polite">
          <header>
            <strong>{active ? `Uploading ${active} of ${items.length}` : `${items.length} uploaded`}</strong>
            <span>{formatBytes(sent)} of {formatBytes(total)}</span>
            {!active && <button className="icon" aria-label="Close" onClick={() => setItems([])}><X size={16} /></button>}
          </header>
          <div className="tray-bar"><span style={{ width: `${total ? (sent / total) * 100 : 0}%` }} /></div>
          {active > 0 && <p className="tray-hint">You can lock your phone: uploading pauses and carries on when you open GharBox again. You'll get a notification when it's done.</p>}
          <ul>
            {items.slice(-50).reverse().map((i) => (
              <li key={i.key} className={i.state}>
                <span className="name" title={i.file.name}>{i.file.name}</span>
                {i.state === "done" && <Check size={15} aria-label="Uploaded" />}
                {i.state === "exists" && <span className="note"><Copy size={13} /> already backed up</span>}
                {i.state === "error" && <span className="note" title={i.error}><AlertCircle size={14} /> {i.error}</span>}
                {i.state === "hashing" && <span className="note">checking</span>}
                {i.state === "uploading" && <span className="note">{Math.round((i.sent / Math.max(i.file.size, 1)) * 100)}%</span>}
              </li>
            ))}
          </ul>
        </aside>
      )}
    </UploadContext.Provider>
  );
}
