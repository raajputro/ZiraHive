// A 10-band equalizer for Listen (songs, audiobooks, Quran recitations).
//
// The player's <audio> element is routed through Web Audio filters: a low shelf, eight peaking
// bands and a high shelf, then a pre-amp. The route is only built the first time the equalizer
// is switched on, so nothing changes for people who never use it. Settings stay on this device:
// the right curve depends on the headphones or speakers, not on the account.

export const BANDS = [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000] as const;
export const MAX_DB = 12;

export type PresetId = "flat" | "bass" | "bassless" | "treble" | "vocal" | "recitation" | "pop" | "rock" | "jazz" | "classical"
  | "dance" | "loudness" | "small" | "night";

/** Gains in dB per band, low to high. */
export const PRESETS: Record<PresetId, number[]> = {
  flat:       [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
  bass:       [6, 5, 4, 2, 0, 0, 0, 0, 0, 0],
  bassless:   [-6, -5, -4, -2, 0, 0, 0, 0, 0, 0],
  treble:     [0, 0, 0, 0, 0, 0, 2, 4, 5, 6],
  vocal:      [-2, -2, -1, 1, 3, 4, 4, 3, 1, 0],
  recitation: [-3, -2, 0, 2, 3, 4, 3, 2, 0, -1],
  pop:        [-1, 1, 3, 4, 3, 0, -1, -1, 1, 2],
  rock:       [5, 4, 2, -1, -2, -1, 2, 3, 4, 4],
  jazz:       [3, 2, 1, 2, -1, -1, 0, 1, 2, 3],
  classical:  [4, 3, 2, 1, -1, -1, 0, 2, 3, 4],
  dance:      [6, 5, 2, 0, 0, -2, -2, -1, 3, 4],
  loudness:   [5, 4, 1, 0, -1, 0, -1, 1, 4, 5],
  small:      [-6, -4, 0, 3, 3, 2, 2, 3, 2, 0],
  night:      [-4, -3, -1, 0, 1, 2, 2, 1, -1, -3],
};

export interface EqSettings {
  enabled: boolean;
  preset: PresetId | "custom";
  gains: number[];   // dB, one per band
  preamp: number;    // dB
}

const KEY = "zirahive.equalizer";
const DEFAULT: EqSettings = { enabled: false, preset: "flat", gains: [...PRESETS.flat], preamp: 0 };

function load(): EqSettings {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return { ...DEFAULT, gains: [...DEFAULT.gains] };
    const s = JSON.parse(raw) as Partial<EqSettings>;
    const gains = Array.isArray(s.gains) && s.gains.length === BANDS.length
      ? s.gains.map((g) => clamp(Number(g) || 0, -MAX_DB, MAX_DB)) : [...DEFAULT.gains];
    const preset = typeof s.preset === "string" && (s.preset === "custom" || s.preset in PRESETS) ? s.preset as EqSettings["preset"] : "custom";
    return { enabled: !!s.enabled, preset, gains, preamp: clamp(Number(s.preamp) || 0, -MAX_DB, MAX_DB) };
  } catch {
    return { ...DEFAULT, gains: [...DEFAULT.gains] };
  }
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

let settings = load();
const listeners = new Set<(s: EqSettings) => void>();

export function getEq(): EqSettings { return settings; }

export function setEq(change: Partial<EqSettings>) {
  settings = { ...settings, ...change, gains: change.gains ? change.gains.map((g) => clamp(g, -MAX_DB, MAX_DB)) : settings.gains };
  try { localStorage.setItem(KEY, JSON.stringify(settings)); } catch { /* private mode: this session only */ }
  apply();
  listeners.forEach((fn) => fn(settings));
}

export function onEq(fn: (s: EqSettings) => void): () => void {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}

/** A gentle cut to the whole signal so boosted bands don't clip: the biggest boost, partly. */
export function autoHeadroom(gains: number[]): number {
  const peak = Math.max(0, ...gains);
  return -Math.round(peak * 0.6 * 10) / 10;
}

// ------------------------------------------------------------------ the audio route

let el: HTMLAudioElement | null = null;
let ctx: AudioContext | null = null;
let filters: BiquadFilterNode[] = [];
let pre: GainNode | null = null;

/** Called by the player with its <audio> element. Builds the route only when the equalizer is on. */
export function attachEqualizer(audio: HTMLAudioElement | null) {
  el = audio;
  if (el && settings.enabled) build();
}

function build() {
  if (!el || ctx) return;
  const AC = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!AC) return;
  try {
    ctx = new AC();
    const source = ctx.createMediaElementSource(el);
    pre = ctx.createGain();
    filters = BANDS.map((f, i) => {
      const b = ctx!.createBiquadFilter();
      b.type = i === 0 ? "lowshelf" : i === BANDS.length - 1 ? "highshelf" : "peaking";
      b.frequency.value = f;
      b.Q.value = 1.1;
      return b;
    });
    let node: AudioNode = source.connect(pre);
    for (const f of filters) node = node.connect(f);
    node.connect(ctx.destination);
    // browsers start an AudioContext paused until someone presses play
    el.addEventListener("play", () => { void ctx?.resume(); });
    if (!el.paused) void ctx.resume();
  } catch {
    ctx = null; filters = []; pre = null;
  }
}

function apply() {
  if (settings.enabled) build();
  if (!ctx || !pre) return;
  const t = ctx.currentTime;
  const on = settings.enabled;
  filters.forEach((f, i) => f.gain.setTargetAtTime(on ? settings.gains[i] : 0, t, 0.03));
  pre.gain.setTargetAtTime(on ? Math.pow(10, settings.preamp / 20) : 1, t, 0.03);
}
