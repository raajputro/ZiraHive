import { useEffect, useRef, useState } from "react";
import ePub, { type Book as EBook, type NavItem, type Rendition } from "epubjs";
import { url } from "../api";
import type { TocEntry, ViewProps } from "../pages/Reader";

const THEMES = {
  light: { body: { color: "#1a1d24 !important", background: "#ffffff !important" }, a: { color: "#2E4A8B !important" } },
  sepia: { body: { color: "#433422 !important", background: "#f4ecd8 !important" }, a: { color: "#8A6A33 !important" } },
  dark: { body: { color: "#dfe3ea !important", background: "#14171d !important" }, a: { color: "#9db4ea !important" } },
};
const FONTS = { publisher: "", serif: "Georgia, 'Noto Serif Bengali', serif", sans: "'Hind Siliguri', system-ui, sans-serif" };
const locKey = (id: string) => `gharbox.epubloc.${id}`;

function flatten(items: NavItem[], depth = 0, out: TocEntry[] = []): TocEntry[] {
  for (const it of items) {
    out.push({ label: it.label.trim(), target: it.href, depth });
    if (it.subitems?.length) flatten(it.subitems, depth + 1, out);
  }
  return out;
}

/** EPUB in paginated mode with epub.js. Scripts inside books never run. */
export default function EpubView({ book, settings, onLocation, onToc, register, onTapMiddle }: ViewProps) {
  const host = useRef<HTMLDivElement>(null);
  const rend = useRef<Rendition | null>(null);
  const ebook = useRef<EBook | null>(null);
  const [error, setError] = useState("");
  const cb = useRef({ onLocation, onTapMiddle });
  cb.current = { onLocation, onTapMiddle };

  useEffect(() => {
    if (!host.current) return;
    const eb = ePub(url.bookFile(book), { openAs: "epub" });
    ebook.current = eb;
    const r = eb.renderTo(host.current, { width: "100%", height: "100%", flow: "paginated", spread: "auto", allowScriptedContent: false } as never);
    rend.current = r;
    (Object.keys(THEMES) as (keyof typeof THEMES)[]).forEach((t) => r.themes.register(t, THEMES[t]));
    let ready = false;
    const located = (where: { start: { cfi: string; percentage: number; displayed: { page: number; total: number } }; atEnd?: boolean }) => {
      const cfi = where.start.cfi;
      const pct = eb.locations.length() ? eb.locations.percentageFromCfi(cfi) : where.start.percentage;
      const chap = where.start.displayed;
      cb.current.onLocation({ fraction: pct || 0, position: 0, locator: cfi, atEnd: !!where.atEnd,
        label: `${Math.round((pct || 0) * 100)}%${chap?.total ? ` · page ${chap.page} of ${chap.total} in this chapter` : ""}` });
    };
    r.on("relocated", (where: never) => { if (ready) located(where); });
    r.on("displayError", () => setError("This book couldn't be shown."));
    // swipe on phones, tap in the middle for the menu
    let sx = 0, sy = 0;
    r.on("touchstart", (e: TouchEvent) => { sx = e.changedTouches[0].screenX; sy = e.changedTouches[0].screenY; });
    r.on("touchend", (e: TouchEvent) => {
      const dx = e.changedTouches[0].screenX - sx, dy = e.changedTouches[0].screenY - sy;
      if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy)) void (dx < 0 ? r.next() : r.prev());
    });
    r.on("click", () => cb.current.onTapMiddle());
    r.on("keyup", (e: KeyboardEvent) => {
      if (e.key === "ArrowRight" || e.key === " ") void r.next();
      if (e.key === "ArrowLeft") void r.prev();
    });

    const start = book.progress?.locator && !book.progress.finished ? book.progress.locator : undefined;
    r.display(start).catch(() => r.display()).then(() => { ready = true; const l = r.currentLocation() as never; if (l) located(l); })
      .catch(() => setError("This book couldn't be opened. It may be damaged or protected (DRM)."));
    eb.loaded.navigation.then((nav) => onToc(flatten(nav.toc))).catch(() => undefined);
    // Locations give a real percentage. They take a moment to work out, so they're kept per book.
    eb.ready.then(async () => {
      let saved: string | null = null;
      try { saved = localStorage.getItem(locKey(book.id)); } catch { /* ignore */ }
      if (saved) eb.locations.load(saved);
      else {
        await eb.locations.generate(1200);
        try { localStorage.setItem(locKey(book.id), eb.locations.save()); } catch { /* full or private */ }
      }
      const l = r.currentLocation() as never;
      if (l && ready) located(l);
    }).catch(() => undefined);

    register({
      next: () => void r.next(),
      prev: () => void r.prev(),
      goTo: (target) => void r.display(target),
      goToFraction: (f) => { if (eb.locations.length()) void r.display(eb.locations.cfiFromPercentage(f)); },
    });
    return () => { eb.destroy(); rend.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [book.id]);

  useEffect(() => {
    const r = rend.current;
    if (!r) return;
    r.themes.select(settings.theme);
    r.themes.fontSize(`${settings.fontSize}%`);
    if (FONTS[settings.font]) r.themes.override("font-family", FONTS[settings.font], true);
    else r.themes.override("font-family", "inherit", false);
  }, [settings.theme, settings.fontSize, settings.font]);

  return (
    <>
      <div className="epub-host" ref={host} />
      {error && <div className="reader-msg"><p className="error">{error}</p></div>}
    </>
  );
}
