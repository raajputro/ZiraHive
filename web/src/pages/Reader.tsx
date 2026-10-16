import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, ChevronLeft, ChevronRight, Download, List, Settings2, X } from "lucide-react";
import { api, ApiError, url, type BookDetail } from "../api";
import { usePrefs } from "../prefs";

import { t as tr } from "../i18n";
const EpubView = lazy(() => import("../readers/EpubView"));
const PdfView = lazy(() => import("../readers/PdfView"));

export interface TocEntry { label: string; target: string; depth: number }

/** What each kind of reader tells the frame, and what the frame can ask of it. */
export interface ReaderApi { next: () => void; prev: () => void; goTo: (target: string) => void; goToFraction: (f: number) => void }
export interface ViewProps {
  book: BookDetail;
  settings: ReaderSettings;
  onLocation: (loc: { fraction: number; position: number; locator?: string; label: string; atEnd: boolean }) => void;
  onToc: (toc: TocEntry[]) => void;
  register: (api: ReaderApi) => void;
  onTapMiddle: () => void;
}
export interface ReaderSettings {
  theme: "light" | "sepia" | "dark";
  fontSize: number;          // percent, EPUB
  font: "publisher" | "serif" | "sans";
  zoom: number;              // PDF
  fit: "width" | "height";   // comics and PDF
  mode: "pages" | "scroll";  // comics
  rtl: boolean;              // comics: right to left (manga)
}

const SETTINGS_KEY = "gharbox.reader";
function loadSettings(): ReaderSettings {
  const base: ReaderSettings = { theme: "light", fontSize: 100, font: "publisher", zoom: 1, fit: "width", mode: "pages", rtl: false };
  try { return { ...base, ...JSON.parse(localStorage.getItem(SETTINGS_KEY) ?? "{}") }; } catch { return base; }
}
function saveSettings(s: ReaderSettings) { try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(s)); } catch { /* private mode */ } }
const rtlKey = (id: string) => `gharbox.rtl.${id}`;

export default function ReaderRoute() {
  const { id } = useParams();
  return id ? <Reader key={id} id={id} /> : null;
}

function Reader({ id }: { id: string }) {
  const navigate = useNavigate();
  const [book, setBook] = useState<BookDetail | null>(null);
  const [error, setError] = useState("");
  const [settings, setSettings] = useState<ReaderSettings>(loadSettings);
  const [chrome, setChrome] = useState(true);
  const [panel, setPanel] = useState<"toc" | "settings" | null>(null);
  const [toc, setToc] = useState<TocEntry[]>([]);
  const [loc, setLoc] = useState<{ fraction: number; label: string; atEnd: boolean }>({ fraction: 0, label: "", atEnd: false });
  const nav = useRef<ReaderApi | null>(null);
  const pending = useRef<{ position: number; fraction: number; locator?: string } | null>(null);
  const timer = useRef<number>();

  useEffect(() => {
    api.book(id).then((b) => {
      setBook(b);
      // manga: the book's own setting, unless you changed it for this book
      let rtl = b.rtl;
      try { const v = localStorage.getItem(rtlKey(b.id)); if (v !== null) rtl = v === "1"; } catch { /* ignore */ }
      setSettings((s) => ({ ...s, rtl }));
    }).catch((e) => setError(e instanceof ApiError ? e.message : tr("Couldn't open this book")));
  }, [id]);

  const change = (c: Partial<ReaderSettings>) => setSettings((s) => {
    const n = { ...s, ...c };
    const { rtl, ...rest } = n;
    saveSettings({ ...loadSettings(), ...rest });
    if (c.rtl !== undefined && book) { try { localStorage.setItem(rtlKey(book.id), rtl ? "1" : "0"); } catch { /* ignore */ } }
    return n;
  });

  // ------------------------------------------------------------ saving progress
  const flush = useCallback(() => {
    window.clearTimeout(timer.current);
    const p = pending.current;
    if (!p || !book) return;
    pending.current = null;
    void api.saveBookProgress(book.id, { ...p, locator: p.locator ?? null }, true).catch(() => undefined);
  }, [book]);

  const onLocation = useCallback((l: { fraction: number; position: number; locator?: string; label: string; atEnd: boolean }) => {
    setLoc({ fraction: l.fraction, label: l.label, atEnd: l.atEnd });
    pending.current = { position: l.position, fraction: l.atEnd ? 1 : l.fraction, locator: l.locator };
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(flush, 1500);
  }, [flush]);

  useEffect(() => {
    const hide = () => { if (document.visibilityState === "hidden") flush(); };
    document.addEventListener("visibilitychange", hide);
    return () => { document.removeEventListener("visibilitychange", hide); flush(); };
  }, [flush]);

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.closest("input, select, textarea")) return;
      if (e.key === "ArrowRight" || e.key === "PageDown" || e.key === " ") { e.preventDefault(); nav.current?.next(); }
      else if (e.key === "ArrowLeft" || e.key === "PageUp") { e.preventDefault(); nav.current?.prev(); }
      else if (e.key === "Escape") { if (panel) setPanel(null); else navigate(-1); }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [panel, navigate]);

  useEffect(() => {
    document.documentElement.dataset.reader = settings.theme;
    return () => { delete document.documentElement.dataset.reader; };
  }, [settings.theme]);

  if (error) return <div className="reader"><div className="reader-msg"><p className="error">{error}</p><Link to="/read">{tr("Back to Read")}</Link></div></div>;
  if (!book) return <div className="reader" aria-busy="true" />;

  const back = () => { flush(); if (window.history.length > 1) navigate(-1); else navigate("/read"); };
  const props: ViewProps = { book, settings, onLocation, onToc: setToc, register: (a) => { nav.current = a; }, onTapMiddle: () => setChrome((c) => !c) };
  const isComic = book.kind === "comic";
  const leftLabel = isComic && settings.rtl ? tr("Next page") : tr("Previous page");
  const rightLabel = isComic && settings.rtl ? tr("Previous page") : tr("Next page");
  const left = () => (isComic && settings.rtl ? nav.current?.next() : nav.current?.prev());
  const right = () => (isComic && settings.rtl ? nav.current?.prev() : nav.current?.next());

  return (
    <div className={`reader theme-${settings.theme} ${chrome ? "" : "bare"}`} role="main" aria-label={tr("Reading {title}", { title: book.title })}>
      <header className="reader-top">
        <button className="icon" onClick={back} aria-label={tr("Close the book")}><ArrowLeft size={20} /></button>
        <span className="reader-title">{book.title}</span>
        {toc.length > 0 && <button className="icon" onClick={() => setPanel(panel === "toc" ? null : "toc")} aria-label={tr("Contents")}><List size={19} /></button>}
        {book.downloadable && <a className="icon" href={url.bookFile(book, true)} aria-label={tr("Download")}><Download size={18} /></a>}
        <button className="icon" onClick={() => setPanel(panel === "settings" ? null : "settings")} aria-label={tr("Reading settings")}><Settings2 size={19} /></button>
      </header>

      <div className="reader-stage">
        <Suspense fallback={<div className="reader-msg" aria-busy="true">{tr("Opening…")}</div>}>
          {book.format === "epub" ? <EpubView {...props} />
            : book.format === "pdf" ? <PdfView {...props} />
            : isComic ? <ComicView {...props} />
            : <div className="reader-msg">{tr("This format can't be read in the browser.")}{" "}<a href={url.bookFile(book, true)}>{tr("Download it")}</a>.</div>}
        </Suspense>
        {!(isComic && settings.mode === "scroll") && <>
          <button className="tap-zone left" onClick={left} aria-label={leftLabel}><ChevronLeft size={28} /></button>
          <button className="tap-zone right" onClick={right} aria-label={rightLabel}><ChevronRight size={28} /></button>
        </>}
        {panel && (
          <aside className="reader-panel" aria-label={panel === "toc" ? tr("Contents") : tr("Reading settings")}>
            <header><strong>{panel === "toc" ? tr("Contents") : tr("Reading settings")}</strong>
              <button className="icon" onClick={() => setPanel(null)} aria-label={tr("Close")}><X size={18} /></button></header>
            {panel === "toc" ? (
              <ol className="toc">
                {toc.map((t, i) => <li key={i} style={{ paddingLeft: t.depth * 14 }}>
                  <button onClick={() => { nav.current?.goTo(t.target); setPanel(null); }}>{t.label}</button></li>)}
              </ol>
            ) : (
              <div className="reader-settings">
                <fieldset><legend>{tr("Page colour")}</legend>
                  {(["light", "sepia", "dark"] as const).map((t) => (
                    <button key={t} className={`swatch ${t} ${settings.theme === t ? "on" : ""}`} aria-pressed={settings.theme === t}
                      onClick={() => change({ theme: t })}>{t[0].toUpperCase() + t.slice(1)}</button>))}
                </fieldset>
                {book.format === "epub" && <>
                  <fieldset><legend>{tr("Text size")}</legend>
                    <button onClick={() => change({ fontSize: Math.max(70, settings.fontSize - 10) })} aria-label={tr("Smaller text")}>{tr("A−")}</button>
                    <span>{settings.fontSize}%</span>
                    <button onClick={() => change({ fontSize: Math.min(200, settings.fontSize + 10) })} aria-label={tr("Larger text")}>{tr("A+")}</button>
                  </fieldset>
                  <label>{tr("Font")}<select value={settings.font} onChange={(e) => change({ font: e.target.value as ReaderSettings["font"] })}>
                      <option value="publisher">{tr("The book's own")}</option><option value="serif">{tr("Serif")}</option><option value="sans">{tr("Sans serif")}</option>
                    </select>
                  </label>
                </>}
                {book.format === "pdf" && (
                  <fieldset><legend>{tr("Zoom")}</legend>
                    <button onClick={() => change({ zoom: Math.max(0.5, +(settings.zoom - 0.25).toFixed(2)) })} aria-label={tr("Zoom out")}>−</button>
                    <span>{Math.round(settings.zoom * 100)}%</span>
                    <button onClick={() => change({ zoom: Math.min(4, +(settings.zoom + 0.25).toFixed(2)) })} aria-label={tr("Zoom in")}>+</button>
                  </fieldset>
                )}
                {(isComic || book.format === "pdf") && (
                  <label>{tr("Fit")}<select value={settings.fit} onChange={(e) => change({ fit: e.target.value as ReaderSettings["fit"] })}>
                      <option value="width">{tr("Fit width")}</option><option value="height">{tr("Whole page")}</option>
                    </select>
                  </label>
                )}
                {isComic && <>
                  <label>{tr("Layout")}<select value={settings.mode} onChange={(e) => change({ mode: e.target.value as ReaderSettings["mode"] })}>
                      <option value="pages">{tr("One page at a time")}</option><option value="scroll">{tr("Scroll down (webtoons)")}</option>
                    </select>
                  </label>
                  <label className="check"><input type="checkbox" checked={settings.rtl} onChange={(e) => change({ rtl: e.target.checked })} />{tr("Right to left (manga)")}</label>
                </>}
              </div>
            )}
          </aside>
        )}
      </div>

      <footer className="reader-bottom">
        <input type="range" min={0} max={1000} value={Math.round(loc.fraction * 1000)} aria-label={tr("Position in the book")}
          onChange={(e) => nav.current?.goToFraction(Number(e.target.value) / 1000)} style={{ direction: isComic && settings.rtl ? "rtl" : "ltr" }} />
        <span className="muted small" aria-live="polite">{loc.label || `${Math.round(loc.fraction * 100)}%`}</span>
        {loc.atEnd && book.next_in_series && (
          <Link className="button primary" to={`/read/book/${book.next_in_series}`} replace onClick={flush}>{tr("Next in series")}</Link>
        )}
      </footer>

    </div>
  );
}

// --------------------------------------------------------------------- comics

const WIDTHS = [720, 1080, 1600, 2400];

function ComicView({ book, settings, onLocation, register, onTapMiddle }: ViewProps) {
  const { lowData } = usePrefs();
  const pages = book.pages ?? 0;
  const startPage = book.progress && !book.progress.finished ? Math.min(pages, Math.max(1, Math.round(book.progress.position) || 1)) : 1;
  const [page, setPage] = useState(startPage);
  const stage = useRef<HTMLDivElement>(null);
  const width = (() => {
    const want = (stage.current?.clientWidth ?? window.innerWidth) * (window.devicePixelRatio || 1);
    const cap = lowData ? 1080 : 2400;
    return WIDTHS.find((w) => w >= Math.min(want, cap)) ?? cap;
  })();
  const src = (n: number) => url.bookPage(book, n, width);

  const show = useCallback((n: number) => setPage(Math.max(1, Math.min(pages, n))), [pages]);
  useEffect(() => {
    register({
      next: () => setPage((p) => Math.min(pages, p + 1)),
      prev: () => setPage((p) => Math.max(1, p - 1)),
      goTo: (t) => show(Number(t)),
      goToFraction: (f) => show(Math.round(f * (pages - 1)) + 1),
    });
  }, [register, pages, show]);

  useEffect(() => {
    onLocation({ fraction: pages > 1 ? (page - 1) / (pages - 1) : 1, position: page, label: `Page ${page} of ${pages}`, atEnd: page >= pages });
    if (settings.mode === "pages") for (const n of [page + 1, page + 2]) if (n <= pages) new Image().src = src(n);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pages]);

  // scroll mode: the page most in view is the current one
  useEffect(() => {
    if (settings.mode !== "scroll" || !stage.current) return;
    const imgs = Array.from(stage.current.querySelectorAll<HTMLImageElement>("img[data-page]"));
    const target = imgs[page - 1];
    target?.scrollIntoView({ block: "start" });
    const io = new IntersectionObserver((entries) => {
      const seen = entries.filter((e) => e.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (seen) setPage(Number((seen.target as HTMLElement).dataset.page));
    }, { root: stage.current, threshold: [0.25, 0.6] });
    imgs.forEach((im) => io.observe(im));
    return () => io.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings.mode]);

  if (!pages) return <div className="reader-msg">{tr("This comic has no pages GharBox can read.")}</div>;
  if (settings.mode === "scroll") {
    return (
      <div className="comic-scroll" ref={stage} onClick={onTapMiddle}>
        {Array.from({ length: pages }, (_, i) => (
          <img key={i} data-page={i + 1} src={src(i + 1)} alt={tr("Page {n}", { n: i + 1 })} loading="lazy" width={width} height={Math.round(width * 1.5)} />
        ))}
      </div>
    );
  }
  return (
    <div className={`comic-page fit-${settings.fit}`} ref={stage} onClick={onTapMiddle}>
      <img key={page} src={src(page)} alt={tr("Page {page} of {pages}", { page: page, pages: pages })} />
    </div>
  );
}
