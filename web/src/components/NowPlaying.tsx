import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronDown, ListMusic, Loader2, Moon, Pause, Play, Repeat, Repeat1, Rewind, FastForward, Shuffle, SkipBack, SkipForward, X } from "lucide-react";
import { clock, useAudio, type Sleep } from "../audio";
import { EqualizerButton } from "./Equalizer";

import { t as tr } from "../i18n";
const RATES = [0.75, 1, 1.1, 1.25, 1.5, 1.75, 2];

/** The bar along the bottom while something plays, and the full "Now playing" panel. */
export default function NowPlaying() {
  const a = useAudio();
  const [open, setOpen] = useState(false);
  const [list, setList] = useState(false);
  useEffect(() => { document.body.classList.toggle("has-player", !!a.current); }, [a.current]);
  useEffect(() => { if (!a.current) setOpen(false); }, [a.current]);
  if (!a.current) return null;

  const isBook = a.current.kind === "book";
  const total = isBook ? (a.book?.duration ?? a.duration) : a.duration;
  const pos = isBook ? a.bookTime : a.time;
  const title = isBook && a.chapter ? a.chapter.title : a.current.title;
  const subtitle = isBook ? a.current.title : a.current.subtitle;
  const seekTo = (v: number) => (isBook ? a.seekBook(v) : a.seek(v));
  const PlayIcon = a.preparing ? Loader2 : a.playing ? Pause : Play;

  return (
    <>
      <div className="np-bar" role="region" aria-label={tr("Now playing")}>
        <div className="np-progress" aria-hidden><span style={{ width: `${total ? Math.min(100, (pos / total) * 100) : 0}%` }} /></div>
        <button className="np-who" onClick={() => setOpen(true)} aria-label={tr("Open now playing")}>
          {a.current.cover ? <img src={a.current.cover} alt="" /> : <span className="np-blank"><ListMusic size={20} /></span>}
          <span className="np-text"><strong>{title}</strong><span>{a.preparing ? tr("Preparing audio…") : a.error || subtitle}</span></span>
        </button>
        <div className="np-buttons">
          {isBook
            ? <button className="icon np-wide" onClick={() => a.skip(-15)} aria-label={tr("Back 15 seconds")}><Rewind size={18} /></button>
            : <button className="icon np-wide" onClick={a.prev} aria-label={tr("Previous")}><SkipBack size={18} /></button>}
          <button className="icon np-play" onClick={a.toggle} aria-label={a.playing ? tr("Pause") : tr("Play")} disabled={a.preparing}>
            <PlayIcon size={20} className={a.preparing ? "spin" : ""} fill={a.preparing ? "none" : "currentColor"} />
          </button>
          {isBook
            ? <button className="icon" onClick={() => a.skip(30)} aria-label={tr("Forward 30 seconds")}><FastForward size={18} /></button>
            : <button className="icon" onClick={a.next} aria-label={tr("Next")} disabled={a.index + 1 >= a.queue.length && a.repeat !== "all"}><SkipForward size={18} /></button>}
        </div>
        <span className="np-time np-wide">{clock(pos)} / {clock(total)}</span>
        <button className="icon np-wide" onClick={a.close} aria-label={tr("Stop and close")}><X size={18} /></button>
      </div>

      {open && (
        <div className="np-panel" role="dialog" aria-label={tr("Now playing")} aria-modal="true">
          <header>
            <button className="icon" onClick={() => setOpen(false)} aria-label={tr("Close")}><ChevronDown size={22} /></button>
            <span className="muted small">{isBook ? tr("Audiobook") : tr("{n} of {total}", { n: a.index + 1, total: a.queue.length })}</span>
            <button className="icon" onClick={() => setList((x) => !x)} aria-pressed={list}
              aria-label={isBook ? tr("Chapters") : tr("Queue")}><ListMusic size={20} /></button>
          </header>
          {!list ? (
            <div className="np-main">
              <div className="np-art">{a.current.cover ? <img src={a.current.cover} alt="" /> : <ListMusic size={64} />}</div>
              <div className="np-titles">
                <h2>{title}</h2>
                <Link to={a.current.link} onClick={() => setOpen(false)} className="muted">{subtitle}</Link>
              </div>
              <input type="range" className="np-seek" min={0} max={Math.max(1, total)} step={1} value={Math.min(pos, total)}
                onChange={(e) => seekTo(Number(e.target.value))} aria-label={tr("Position")} />
              <div className="np-times"><span>{clock(pos)}</span><span>-{clock(Math.max(0, total - pos))}</span></div>
              {a.error && <p className="error" role="alert">{a.error}</p>}
              <div className="np-controls">
                {isBook
                  ? <button className="icon" onClick={() => a.skip(-15)} aria-label={tr("Back 15 seconds")}><Rewind size={22} /><small>15</small></button>
                  : <button className={`icon ${a.shuffle ? "on" : ""}`} onClick={a.toggleShuffle} aria-pressed={a.shuffle} aria-label={tr("Shuffle")}><Shuffle size={20} /></button>}
                <button className="icon" onClick={isBook ? () => a.seekBook(prevChapterStart(a)) : a.prev} aria-label={isBook ? tr("Previous chapter") : tr("Previous")}><SkipBack size={24} /></button>
                <button className="icon np-big" onClick={a.toggle} aria-label={a.playing ? tr("Pause") : tr("Play")} disabled={a.preparing}>
                  <PlayIcon size={30} className={a.preparing ? "spin" : ""} fill={a.preparing ? "none" : "currentColor"} />
                </button>
                <button className="icon" onClick={isBook ? () => nextChapter(a) : a.next} aria-label={isBook ? tr("Next chapter") : tr("Next")}><SkipForward size={24} /></button>
                {isBook
                  ? <button className="icon" onClick={() => a.skip(30)} aria-label={tr("Forward 30 seconds")}><FastForward size={22} /><small>30</small></button>
                  : <button className={`icon ${a.repeat !== "off" ? "on" : ""}`} onClick={a.cycleRepeat} aria-label={tr("Repeat: {repeat}", { repeat: a.repeat })}>
                      {a.repeat === "one" ? <Repeat1 size={20} /> : <Repeat size={20} />}</button>}
              </div>
              <div className="np-extra">
                {isBook && (
                  <label>{tr("Speed")}<select value={a.rate} onChange={(e) => a.setRate(Number(e.target.value))}>
                      {RATES.map((r) => <option key={r} value={r}>{r}×</option>)}
                    </select>
                  </label>
                )}
                <SleepMenu isBook={isBook} />
                <EqualizerButton />
              </div>
            </div>
          ) : isBook ? (
            <ol className="np-list">
              {a.book?.chapters.map((c, i) => (
                <li key={i} className={a.chapter === c ? "now" : ""}>
                  <button onClick={() => a.seekBook(c.start)}><span>{c.title}</span><span className="muted small">{clock(c.start)}</span></button>
                </li>
              ))}
            </ol>
          ) : (
            <ol className="np-list">
              {a.queue.map((q, i) => (
                <li key={q.key} className={i === a.index ? "now" : ""}>
                  <button onClick={() => a.jump(i)}><span>{q.title}<span className="muted small"> {q.subtitle}</span></span>
                    <span className="muted small">{clock(q.duration)}</span></button>
                  {i !== a.index && <button className="icon" onClick={() => a.remove(i)} aria-label={tr("Remove {title} from the queue", { title: q.title })}><X size={15} /></button>}
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </>
  );
}

function prevChapterStart(a: ReturnType<typeof useAudio>): number {
  const chs = a.book?.chapters ?? [];
  const i = a.chapter ? chs.indexOf(a.chapter) : 0;
  // like a CD player: back to the start of this chapter, or the one before if we're near its start
  if (a.chapter && a.bookTime - a.chapter.start > 4) return a.chapter.start;
  return chs[Math.max(0, i - 1)]?.start ?? 0;
}

function nextChapter(a: ReturnType<typeof useAudio>) {
  const chs = a.book?.chapters ?? [];
  const nxt = chs.find((c) => c.start > a.bookTime + 0.5);
  if (nxt) a.seekBook(nxt.start);
}

function SleepMenu({ isBook }: { isBook: boolean }) {
  const a = useAudio();
  const [, tick] = useState(0);
  useEffect(() => { const t = setInterval(() => tick((x) => x + 1), 15_000); return () => clearInterval(t); }, []);
  const left = a.sleep && "until" in a.sleep ? Math.max(1, Math.round((a.sleep.until - Date.now()) / 60000)) : null;
  const value = !a.sleep ? "off" : "until" in a.sleep ? "timer" : a.sleep.end;
  const choose = (v: string) => {
    const s: Sleep = v === "off" ? null : v === "chapter" || v === "track" ? { end: v } : { until: Date.now() + Number(v) * 60000 };
    a.setSleep(s);
  };
  return (
    <label><span><Moon size={14} aria-hidden />{" "}{tr("Sleep")}</span>
      <select value={value} onChange={(e) => choose(e.target.value)}>
        <option value="off">{tr("Off")}</option>
        {value === "timer" && <option value="timer">{left}{" "}{tr("min left")}</option>}
        {[10, 15, 30, 45, 60, 90].map((m) => <option key={m} value={m}>{m}{" "}{tr("minutes")}</option>)}
        <option value={isBook ? "chapter" : "track"}>{isBook ? tr("End of chapter") : tr("End of this song")}</option>
      </select>
    </label>
  );
}
