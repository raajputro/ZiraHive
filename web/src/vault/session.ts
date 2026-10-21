// The unlocked master key lives only in this tab's memory. It is never stored, and it is
// forgotten after a few minutes without activity (5 unless changed on this browser), when you
// press Lock, or when the tab closes.
import { useEffect, useState } from "react";

export const LOCK_DEFAULT = 5, LOCK_MIN = 1, LOCK_MAX = 120;
const LOCK_KEY = "zirahive.vault.lockMinutes";
const clampMinutes = (n: number) => Math.min(LOCK_MAX, Math.max(LOCK_MIN, Math.round(n)));
/** Minutes without activity before the vault locks itself, on this browser. */
export function lockMinutes(): number {
  try { const v = Number(localStorage.getItem(LOCK_KEY)); if (v) return clampMinutes(v); } catch { /* private mode */ }
  return LOCK_DEFAULT;
}
export function setLockMinutes(n: number) {
  try { localStorage.setItem(LOCK_KEY, String(clampMinutes(n))); } catch { /* private mode: this tab only */ }
  touch();  // restart the countdown with the new length
  emit();
}
let master: CryptoKey | null = null;
let masterRaw: Uint8Array | null = null;
let timer = 0;
const listeners = new Set<() => void>();

function emit() { listeners.forEach((fn) => fn()); }

function touch() {
  if (!master) return;
  window.clearTimeout(timer);
  timer = window.setTimeout(lock, lockMinutes() * 60 * 1000);
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
