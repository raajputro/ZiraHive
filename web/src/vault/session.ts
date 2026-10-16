// The unlocked master key lives only in this tab's memory. It is never stored, and it is
// forgotten after 10 minutes without activity, when you press Lock, or when the tab closes.
import { useEffect, useState } from "react";

const IDLE_MS = 10 * 60 * 1000;
let master: CryptoKey | null = null;
let masterRaw: Uint8Array | null = null;
let timer = 0;
const listeners = new Set<() => void>();

function emit() { listeners.forEach((fn) => fn()); }

function touch() {
  if (!master) return;
  window.clearTimeout(timer);
  timer = window.setTimeout(lock, IDLE_MS);
}

export function unlock(key: CryptoKey, raw: Uint8Array) {
  master = key;
  masterRaw = raw;
  touch();
  emit();
}

export function lock() {
  window.clearTimeout(timer);
  masterRaw?.fill(0);
  master = null;
  masterRaw = null;
  emit();
}

export const masterKey = () => master;
export const masterBytes = () => masterRaw;

for (const ev of ["pointerdown", "keydown", "scroll"]) window.addEventListener(ev, touch, { passive: true });

/** Re-renders when the vault locks or unlocks. */
export function useVaultKey(): CryptoKey | null {
  const [, set] = useState(0);
  useEffect(() => { const fn = () => set((x) => x + 1); listeners.add(fn); return () => { listeners.delete(fn); }; }, []);
  return master;
}
