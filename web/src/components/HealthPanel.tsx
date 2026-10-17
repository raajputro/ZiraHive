import { useEffect, useState } from "react";
import { Activity, AlertTriangle, Check, Info, X } from "lucide-react";
import { api, type HealthItem } from "../api";
import { t as tr, tx } from "../i18n";

const ICON = { ok: Check, warn: AlertTriangle, fail: X, info: Info };

/** Settings > Server > Health: everything ZiraHive needs, and what to do about what's missing. */
export default function HealthPanel() {
  const [items, setItems] = useState<HealthItem[] | null>(null);
  const load = () => { setItems(null); api.health().then(setItems).catch(() => setItems([])); };
  useEffect(load, []);
  const bad = items?.filter((i) => i.status === "fail" || i.status === "warn").length ?? 0;
  return (
    <section className="panel health">
      <h2><Activity size={18} aria-hidden />{" "}{tr("Health")}</h2>
      {items === null ? <p className="muted" aria-busy="true">{tr("Checking…")}</p> : (
        <>
          <p className={bad ? "" : "muted"}>{bad ? tr("{n} things need a look.", { n: bad }) : tr("Everything ZiraHive needs is working.")}</p>
          <ul className="health-list">
            {items.map((i) => {
              const Icon = ICON[i.status];
              return (
                <li key={i.id} className={`health-${i.status}`}>
                  <Icon size={16} aria-label={tr(i.status === "ok" ? "OK" : i.status === "fail" ? "Problem" : i.status === "warn" ? "Needs a look" : "Note")} />
                  <div>
                    <strong>{tx(i.title)}</strong>{" "}<span className="muted small">{tx(i.detail)}</span>
                    {i.fix && <p className="small">{tx(i.fix)}</p>}
                  </div>
                </li>
              );
            })}
          </ul>
          <button onClick={load}>{tr("Check again")}</button>
        </>
      )}
    </section>
  );
}
