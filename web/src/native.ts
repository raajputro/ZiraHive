// When ZiraHive runs inside the Android app, the app adds `window.ZiraHiveApp` (android/.../WebBridge.kt)
// so pages can use the phone's own player, backup settings and so on. In a browser it's undefined.

export interface NativePlaySpec {
  url: string;
  /** Tried when `url` won't play (a format the phone can't handle): the server-converted stream. */
  fallbackUrl?: string;
  title: string;
  subtitle?: string | null;
  poster?: string | null;
  start?: number;
  live?: boolean;
  content_type?: string;
  /** A library title: the app saves the watch position on the server itself. */
  mediaId?: string;
  /** Anything else to hand back when the player closes (e.g. where to remember the position). */
  key?: string;
  subtitles?: { url: string; label: string; language: string | null }[];
  playlist?: { url: string; title: string; live?: boolean }[];
  index?: number;
}

export interface PlayerClosed {
  position: number; duration: number | null; index: number; finished: boolean;
  mediaId: string | null; key: string | null;
}

interface Bridge {
  version(): string;
  play(spec: string): void;
  openBackupSettings(): void;
  openAddressSettings(): void;
  backupStatus(): string;
  signedOut(): void;
}

const bridge = (window as unknown as { ZiraHiveApp?: Bridge }).ZiraHiveApp;

export const inApp = !!bridge;

export const nativeApp = bridge ? {
  version: (): { name: string; code: number; device: string } => JSON.parse(bridge.version()),
  /** Plays in the app's player. Relative addresses are made absolute (the player isn't a page). */
  play: (spec: NativePlaySpec) => {
    const abs = (u: string) => new URL(u, location.origin).toString();
    bridge.play(JSON.stringify({
      ...spec, url: abs(spec.url), fallbackUrl: spec.fallbackUrl ? abs(spec.fallbackUrl) : undefined,
      subtitles: spec.subtitles?.map((s) => ({ ...s, url: abs(s.url) })),
      playlist: spec.playlist?.map((p) => ({ ...p, url: abs(p.url) })),
    }));
  },
  openBackupSettings: () => bridge.openBackupSettings(),
  openAddressSettings: () => bridge.openAddressSettings(),
  backupStatus: (): { enabled: boolean; running: boolean; lastRun: number; uploaded: number; permission: boolean } =>
    JSON.parse(bridge.backupStatus()),
  signedOut: () => { try { bridge.signedOut(); } catch { /* older app */ } },
} : null;

/** Runs `fn` once when the app's player closes. Returns a function that stops listening. */
export function onPlayerClosed(fn: (r: PlayerClosed) => void): () => void {
  const handler = (e: Event) => fn((e as CustomEvent<PlayerClosed>).detail);
  window.addEventListener("zirahive:player-closed", handler);
  return () => window.removeEventListener("zirahive:player-closed", handler);
}
