// Interface languages. English text is the key; other languages map it to their own text.
//   t("Watch parties")                 -> "ওয়াচ পার্টি"
//   t("{n} songs", { n: 12 })          -> "১২টি গান"
// Messages that arrive from the server ("3 new songs in Music") are matched against keys with
// {placeholders} too, so they show in Bangla without the server knowing the language.
import bn from "./locales/bn";

export type Lang = "en" | "bn";
const DICTS: Record<Lang, Record<string, string>> = { en: {}, bn };
const KEY = "gharbox.lang";

function initial(): Lang {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "en" || saved === "bn") return saved;
  } catch { /* private mode */ }
  return navigator.languages?.some((l) => l.toLowerCase().startsWith("bn")) ? "bn" : "en";
}

let current: Lang = initial();
document.documentElement.lang = current;

export const lang = () => current;
export const locale = () => (current === "bn" ? "bn-BD" : undefined);

/** Change the language and reload, so every screen shows it. */
export function setLang(l: Lang, reload = true) {
  try { localStorage.setItem(KEY, l); } catch { /* ignore */ }
  if (l !== current && reload) location.reload();
  current = l;
}

/** Called after sign-in: the account's language wins over this browser's guess. */
export function adoptAccountLanguage(l: string | null | undefined) {
  if ((l === "en" || l === "bn") && l !== current) setLang(l);
}

const BN_DIGITS = "০১২৩৪৫৬৭৮৯";
/** 1234 -> "১,২৩৪" in Bangla, "1,234" in English. */
export function num(n: number, opts?: Intl.NumberFormatOptions): string {
  return n.toLocaleString(locale() ?? "en", opts);
}
/** Swaps 0-9 for Bangla digits in already-formatted text (times like 3:05, sizes like 1.2 GB). */
export function digits(s: string): string {
  return current === "bn" ? s.replace(/\d/g, (d) => BN_DIGITS[Number(d)]) : s;
}

function fill(template: string, vars?: Record<string, unknown>): string {
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (_, k) => {
    const v = vars[k];
    if (v === undefined || v === null) return "";
    return typeof v === "number" ? num(v) : String(v);
  });
}

export function t(text: string, vars?: Record<string, unknown>): string {
  const tr = DICTS[current][text];
  return fill(tr ?? text, vars);
}

// ------------------------------------------------- text that comes from the server
let patterns: { re: RegExp; names: string[]; out: string }[] | null = null;

function compile() {
  patterns = [];
  for (const [key, out] of Object.entries(DICTS[current])) {
    if (!key.includes("{")) continue;
    const names: string[] = [];
    const src = key.replace(/[.*+?^$()|[\]\\]/g, "\\$&").replace(/\\?\{(\w+)\\?\}/g, (_, n) => { names.push(n); return "(.+?)"; });
    patterns.push({ re: new RegExp(`^${src}$`), names, out });
  }
}

/** Translate a whole sentence from the server, including ones with names and numbers in them. */
export function tx(text: string | null | undefined): string {
  if (!text) return "";
  if (current === "en") return text;
  const exact = DICTS[current][text];
  if (exact) return exact;
  if (!patterns) compile();
  for (const p of patterns!) {
    const m = text.match(p.re);
    if (m) {
      const vars: Record<string, unknown> = {};
      p.names.forEach((n, i) => {
        const v = m[i + 1];
        vars[n] = /^\d+$/.test(v) ? Number(v) : /^[\d.,% ]+$/.test(v) ? digits(v) : t(v);
      });
      return fill(p.out, vars);
    }
  }
  return text;
}
