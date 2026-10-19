// The equalizer panel: on/off, presets, ten sliders and a pre-amp, with the curve drawn above them.
import { useEffect, useState } from "react";
import { SlidersHorizontal } from "lucide-react";
import Dialog from "./Dialog";
import { autoHeadroom, BANDS, getEq, MAX_DB, onEq, PRESETS, setEq, type EqSettings, type PresetId } from "../equalizer";
import { digits, t as tr } from "../i18n";

function presetLabel(p: PresetId | "custom"): string {
  switch (p) {
    case "flat": return tr("Flat");
    case "bass": return tr("Bass boost");
    case "bassless": return tr("Less bass");
    case "treble": return tr("Treble boost");
    case "vocal": return tr("Vocals");
    case "recitation": return tr("Quran recitation (clear voice)");
    case "pop": return tr("Pop");
    case "rock": return tr("Rock");
    case "jazz": return tr("Jazz");
    case "classical": return tr("Classical");
    case "dance": return tr("Dance");
    case "loudness": return tr("Loudness");
    case "small": return tr("Small speakers");
    case "night": return tr("Night (quiet, no boom)");
    case "custom": return tr("Custom");
  }
}

const bandLabel = (f: number) => digits(f >= 1000 ? `${f / 1000}k` : String(f));

export function useEq(): EqSettings {
  const [s, setS] = useState(getEq());
  useEffect(() => onEq(setS), []);
  return s;
}

/** A small button that opens the panel; it shows "on" while the equalizer is shaping the sound. */
export function EqualizerButton({ label = true }: { label?: boolean }) {
  const [open, setOpen] = useState(false);
  const eq = useEq();
  return (
    <>
      <button type="button" className={`eq-button ${eq.enabled ? "on" : ""} ${label ? "" : "icon"}`} onClick={() => setOpen(true)}
        aria-label={tr("Equalizer")} title={tr("Equalizer")} aria-haspopup="dialog">
        <SlidersHorizontal size={16} aria-hidden />{label && <>{" "}{tr("Equalizer")}</>}
      </button>
      {open && <EqualizerDialog onClose={() => setOpen(false)} />}
    </>
  );
}

function Curve({ gains, preamp, enabled }: { gains: number[]; preamp: number; enabled: boolean }) {
  const w = 300, h = 90, pad = 8;
  const x = (i: number) => pad + (i * (w - 2 * pad)) / (gains.length - 1);
  const y = (db: number) => h / 2 - (db / MAX_DB) * (h / 2 - pad);
  const pts = gains.map((g, i) => [x(i), y(enabled ? g + preamp : 0)] as const);
  // a smooth line through the points (Catmull-Rom as cubic Béziers)
  let d = `M${pts[0][0]},${pts[0][1]}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[Math.max(0, i - 1)], p1 = pts[i], p2 = pts[i + 1], p3 = pts[Math.min(pts.length - 1, i + 2)];
    d += ` C${p1[0] + (p2[0] - p0[0]) / 6},${p1[1] + (p2[1] - p0[1]) / 6} ${p2[0] - (p3[0] - p1[0]) / 6},${p2[1] - (p3[1] - p1[1]) / 6} ${p2[0]},${p2[1]}`;
  }
  return (
    <svg className={`eq-curve ${enabled ? "" : "off"}`} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden>
      <line x1={pad} x2={w - pad} y1={h / 2} y2={h / 2} className="eq-zero" />
      <path d={`${d} L${w - pad},${h} L${pad},${h} Z`} className="eq-fill" />
      <path d={d} className="eq-line" />
    </svg>
  );
}

export default function EqualizerDialog({ onClose }: { onClose: () => void }) {
  const eq = useEq();
  const pick = (p: PresetId) => setEq({ preset: p, gains: [...PRESETS[p]], preamp: autoHeadroom(PRESETS[p]), enabled: true });
  const band = (i: number, v: number) => {
    const gains = eq.gains.map((g, j) => (j === i ? v : g));
    setEq({ gains, preset: "custom", enabled: true });
  };
  return (
    <Dialog title={tr("Equalizer")} onClose={onClose} wide>
      <div className="eq">
        <div className="eq-top">
          <label className="toggle-row">
            <input type="checkbox" checked={eq.enabled} onChange={(e) => setEq({ enabled: e.target.checked })} />
            {" "}{eq.enabled ? tr("On") : tr("Off")}
          </label>
          <label>{tr("Preset")}
            <select value={eq.preset} onChange={(e) => e.target.value !== "custom" && pick(e.target.value as PresetId)}>
              {(Object.keys(PRESETS) as PresetId[]).map((p) => <option key={p} value={p}>{presetLabel(p)}</option>)}
              {eq.preset === "custom" && <option value="custom">{presetLabel("custom")}</option>}
            </select>
          </label>
          <button type="button" onClick={() => pick("flat")}>{tr("Reset")}</button>
        </div>
        <Curve gains={eq.gains} preamp={eq.preamp} enabled={eq.enabled} />
        <div className={`eq-bands ${eq.enabled ? "" : "off"}`}>
          {BANDS.map((f, i) => (
            <label key={f} className="eq-band">
              <span className="eq-db">{digits(`${eq.gains[i] > 0 ? "+" : ""}${eq.gains[i]}`)}</span>
              <input type="range" min={-MAX_DB} max={MAX_DB} step={1} value={eq.gains[i]}
                onChange={(e) => band(i, Number(e.target.value))}
                aria-label={tr("{hz} Hz", { hz: f })} aria-valuetext={tr("{db} dB", { db: eq.gains[i] })} />
              <span className="eq-hz">{bandLabel(f)}</span>
            </label>
          ))}
        </div>
        <label className="eq-preamp">{tr("Pre-amp")} <span className="muted small">{digits(`${eq.preamp > 0 ? "+" : ""}${eq.preamp} dB`)}</span>
          <input type="range" min={-MAX_DB} max={6} step={0.5} value={eq.preamp}
            onChange={(e) => setEq({ preamp: Number(e.target.value), enabled: true })} />
        </label>
        <p className="muted small">{tr("Lower the pre-amp if loud parts crackle. These settings stay on this device, so phones and speakers can each have their own.")}</p>
      </div>
    </Dialog>
  );
}
