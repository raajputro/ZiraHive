// The top of every section (title and buttons, then the tabs or search bar under it) stays in view
// while the page scrolls. CSS does the sticking ([data-sticky] in styles.css); this marks which
// elements those are on the current page and keeps two measurements up to date:
//   --head-h    height of the title row, where the tab bar sticks
//   --sticky-h  height of the whole stuck block, so other sticky things (Photos month titles,
//               the Live TV player) sit below it, and so keyboard focus scrolls clear of it
// The elements are marked with data attributes, which React leaves alone when it re-renders.
import { useEffect } from "react";

/** What counts as "the bar under the title": section tabs, Watch/Photos tab-and-search rows, the Files search. */
const BAR = ".watch-bar, .settings-tabs, .files-search, .lib-tabs";

export function useStickyHeads() {
  useEffect(() => {
    const root = document.documentElement;
    let head: HTMLElement | null = null, bar: HTMLElement | null = null, frame = 0;
    const sizes = new ResizeObserver(() => measure());

    function measure() {
      const h = head?.offsetHeight ?? 0;
      root.style.setProperty("--head-h", `${h}px`);
      root.style.setProperty("--sticky-h", `${h + (bar?.offsetHeight ?? 0)}px`);
      onScroll();
    }
    function onScroll() {
      // a thin line under the stuck block once something has scrolled beneath it
      const last = bar ?? head;
      if (last) last.toggleAttribute("data-scrolled", window.scrollY > 4);
    }
    function find() {
      frame = 0;
      const page = document.querySelector<HTMLElement>("main .page");
      const first = page?.firstElementChild as HTMLElement | null | undefined;
      const newHead = first?.matches(".page-head") ? first : null;
      const next = (newHead ? newHead.nextElementSibling : first) as HTMLElement | null | undefined;
      const newBar = next?.matches(BAR) ? next : null;
      if (newHead === head && newBar === bar) return;
      for (const el of [head, bar]) { el?.removeAttribute("data-sticky"); el?.removeAttribute("data-scrolled"); }
      sizes.disconnect();
      head = newHead; bar = newBar;
      head?.setAttribute("data-sticky", "head");
      bar?.setAttribute("data-sticky", bar === first ? "only" : "bar");
      for (const el of [head, bar]) if (el) sizes.observe(el);
      measure();
    }
    const schedule = () => { if (!frame) frame = requestAnimationFrame(find); };
    const changes = new MutationObserver(schedule);
    const main = document.querySelector("main");
    if (main) changes.observe(main, { childList: true, subtree: true });
    window.addEventListener("scroll", onScroll, { passive: true });
    schedule();
    return () => {
      changes.disconnect(); sizes.disconnect();
      window.removeEventListener("scroll", onScroll);
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);
}
