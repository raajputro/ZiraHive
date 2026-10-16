import { useCallback, useEffect, useRef, useState } from "react";
import * as pdfjs from "pdfjs-dist";
import type { PDFDocumentProxy, RenderTask } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { url } from "../api";
import type { TocEntry, ViewProps } from "../pages/Reader";

import { t as tr } from "../i18n";
pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

/** PDF one page at a time with pdf.js, sharp on high-density screens. */
export default function PdfView({ book, settings, onLocation, onToc, register, onTapMiddle }: ViewProps) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [error, setError] = useState("");
  const startPage = book.progress && !book.progress.finished ? Math.max(1, Math.round(book.progress.position) || 1) : 1;
  const [page, setPage] = useState(startPage);
  const task = useRef<RenderTask | null>(null);
  const [size, setSize] = useState(0);

  useEffect(() => {
    // isEvalSupported off: pdf.js never builds code from the file (and the page's CSP forbids it anyway)
    const loading = pdfjs.getDocument({ url: url.bookFile(book), isEvalSupported: false, withCredentials: true });
    loading.promise.then(async (d) => {
      setDoc(d);
      setPage((p) => Math.min(p, d.numPages));
      const outline = await d.getOutline().catch(() => null);
      if (outline) {
        const out: TocEntry[] = [];
        const walk = async (items: typeof outline, depth: number) => {
          for (const it of items) {
            try {
              const dest = typeof it.dest === "string" ? await d.getDestination(it.dest) : it.dest;
              if (dest) out.push({ label: it.title, target: String((await d.getPageIndex(dest[0] as never)) + 1), depth });
            } catch { /* skip broken entries */ }
            if (it.items?.length) await walk(it.items, depth + 1);
          }
        };
        await walk(outline, 0);
        onToc(out);
      }
    }).catch((e) => setError(e?.name === "PasswordException" ? tr("This PDF is protected with a password.") : tr("This PDF couldn't be opened.")));
    return () => { void loading.destroy(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [book.id]);

  const pages = doc?.numPages ?? book.pages ?? 1;
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pages]);

  useEffect(() => {
    const ro = new ResizeObserver(() => setSize((s) => s + 1));
    if (stage.current) ro.observe(stage.current);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    if (!doc || !canvas.current || !stage.current) return;
    let cancelled = false;
    void doc.getPage(page).then((p) => {
      if (cancelled || !canvas.current || !stage.current) return;
      const base = p.getViewport({ scale: 1 });
      const box = stage.current.getBoundingClientRect();
      const fitW = (box.width - 16) / base.width, fitH = (box.height - 16) / base.height;
      const scale = (settings.fit === "height" ? Math.min(fitW, fitH) : fitW) * settings.zoom;
      const dpr = Math.min(window.devicePixelRatio || 1, 3);
      const vp = p.getViewport({ scale });
      const c = canvas.current;
      c.width = Math.floor(vp.width * dpr);
      c.height = Math.floor(vp.height * dpr);
      c.style.width = `${Math.floor(vp.width)}px`;
      c.style.height = `${Math.floor(vp.height)}px`;
      task.current?.cancel();
      task.current = p.render({ canvasContext: c.getContext("2d")!, viewport: vp, transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : undefined });
      task.current.promise.catch(() => undefined);
      stage.current.scrollTop = 0;
    });
    return () => { cancelled = true; };
  }, [doc, page, settings.fit, settings.zoom, size]);

  if (error) return <div className="reader-msg"><p className="error">{error}</p></div>;
  return (
    <div className={`pdf-stage theme-${settings.theme}`} ref={stage} onClick={onTapMiddle}>
      <canvas ref={canvas} aria-label={tr("Page {page} of {pages}", { page: page, pages: pages })} role="img" />
    </div>
  );
}
