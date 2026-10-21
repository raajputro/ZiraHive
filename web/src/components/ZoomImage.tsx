// A photo you can zoom: pinch with two fingers, double-tap (or double-click), mouse wheel, and
// drag to look around once zoomed. Not zoomed, a sideways swipe goes to the next/previous photo.
// The Android app turns off page zoom (so buttons don't zoom by accident), so this is how
// photos zoom there; it works the same in browsers.
import { useEffect, useRef, useState, type ImgHTMLAttributes } from "react";

const MAX = 6;
const DOUBLE_TAP = 300;   // ms
const SWIPE = 60;         // px

type View = { s: number; x: number; y: number };
const NONE: View = { s: 1, x: 0, y: 0 };

export default function ZoomImage({ onSwipe, ...img }: ImgHTMLAttributes<HTMLImageElement> & {
  onSwipe?: (dir: "next" | "prev") => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const pic = useRef<HTMLImageElement>(null);
  const [view, setView] = useState<View>(NONE);
  const [moving, setMoving] = useState(false);
  const v = useRef(view);
  v.current = view;
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const gesture = useRef<{ startX: number; startY: number; dist: number; base: View; mid: { x: number; y: number }; t: number } | null>(null);
  const lastTap = useRef(0);

  useEffect(() => { setView(NONE); }, [img.src]);

  /** Keeps the photo covering the screen edge to edge while zoomed: no empty space to drag into. */
  const clamp = (n: View): View => {
    const el = pic.current, b = box.current;
    if (!el || !b || n.s <= 1) return NONE;
    const w = el.offsetWidth * n.s, h = el.offsetHeight * n.s;
    const mx = Math.max(0, (w - b.clientWidth) / 2), my = Math.max(0, (h - b.clientHeight) / 2);
    return { s: n.s, x: Math.max(-mx, Math.min(mx, n.x)), y: Math.max(-my, Math.min(my, n.y)) };
  };

  /** Zoom to scale `s` keeping the point under (clientX, clientY) where it is. */
  const zoomAt = (s: number, clientX: number, clientY: number, from: View = v.current) => {
    const b = box.current!.getBoundingClientRect();
    const px = clientX - (b.left + b.width / 2), py = clientY - (b.top + b.height / 2);
    const ns = Math.max(1, Math.min(MAX, s));
    const k = ns / from.s;
    return clamp({ s: ns, x: px - (px - from.x) * k, y: py - (py - from.y) * k });
  };

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    const pts = [...pointers.current.values()];
    const mid = pts.length === 2 ? { x: (pts[0].x + pts[1].x) / 2, y: (pts[0].y + pts[1].y) / 2 } : { x: e.clientX, y: e.clientY };
    const dist = pts.length === 2 ? Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y) : 0;
    gesture.current = { startX: mid.x, startY: mid.y, dist, base: v.current, mid, t: Date.now() };
    setMoving(true);
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!pointers.current.has(e.pointerId) || !gesture.current) return;
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    const g = gesture.current;
    const pts = [...pointers.current.values()];
    if (pts.length === 2 && g.dist > 0) {
      const dist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
      const mid = { x: (pts[0].x + pts[1].x) / 2, y: (pts[0].y + pts[1].y) / 2 };
      const zoomed = zoomAt(g.base.s * (dist / g.dist), g.mid.x, g.mid.y, g.base);
      // and follow the fingers as they move together
      setView(clamp({ ...zoomed, x: zoomed.x + mid.x - g.mid.x, y: zoomed.y + mid.y - g.mid.y }));
    } else if (pts.length === 1 && g.base.s > 1) {
      setView(clamp({ s: g.base.s, x: g.base.x + e.clientX - g.startX, y: g.base.y + e.clientY - g.startY }));
    }
  };

  const onPointerUp = (e: React.PointerEvent) => {
    const g = gesture.current;
    const wasOne = pointers.current.size === 1;
    pointers.current.delete(e.pointerId);
    if (pointers.current.size > 0) {
      // one finger lifted from a pinch: carry on dragging with the other
      const [p] = [...pointers.current.values()];
      gesture.current = { startX: p.x, startY: p.y, dist: 0, base: v.current, mid: p, t: Date.now() };
      return;
    }
    setMoving(false);
    gesture.current = null;
    if (!g || !wasOne) return;
    const dx = e.clientX - g.startX, dy = e.clientY - g.startY;
    const still = Math.abs(dx) < 10 && Math.abs(dy) < 10;
    if (still && Date.now() - g.t < 250) {
      // a tap: two quick ones zoom in, or back out
      const now = Date.now();
      if (now - lastTap.current < DOUBLE_TAP) {
        lastTap.current = 0;
        setView(v.current.s > 1 ? NONE : zoomAt(2.5, e.clientX, e.clientY));
      } else lastTap.current = now;
      return;
    }
    if (g.base.s <= 1 && onSwipe && Math.abs(dx) > SWIPE && Math.abs(dx) > Math.abs(dy) * 1.5) {
      onSwipe(dx < 0 ? "next" : "prev");
    }
  };

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      setView((cur) => zoomAt(cur.s * Math.exp(-e.deltaY * 0.0015), e.clientX, e.clientY, cur));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div ref={box} className={`zoom-box ${view.s > 1 ? "zoomed" : ""} ${moving ? "moving" : ""}`}
      onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp}>
      <img ref={pic} draggable={false} {...img}
        style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.s})`, ...img.style }} />
    </div>
  );
}
