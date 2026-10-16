import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Bell } from "lucide-react";
import { api, type Notice } from "../api";

import { locale, t as tr, tx } from "../i18n";
const when = new Intl.RelativeTimeFormat(locale(), { numeric: "auto" });
function ago(iso: string) {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 60) return when.format(-mins, "minute");
  if (mins < 1440) return when.format(-Math.round(mins / 60), "hour");
  return when.format(-Math.round(mins / 1440), "day");
}

export default function NotificationBell() {
  const [items, setItems] = useState<Notice[]>([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  const load = () => api.notifications().then((n) => { setItems(n.items); setUnread(n.unread); }).catch(() => undefined);
  useEffect(() => { void load(); const t = setInterval(load, 60_000); return () => clearInterval(t); }, []);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const toggle = () => {
    setOpen(!open);
    if (!open && unread) { void api.markNotificationsRead().then(() => setUnread(0)); }
  };

  return (
    <div className="bell" ref={box}>
      <button className="icon" onClick={toggle} aria-label={unread ? tr("Notifications, {n} new", { n: unread }) : tr("Notifications")} aria-expanded={open}>
        <Bell size={18} />
        {unread > 0 && <span className="badge">{unread > 9 ? "9+" : unread}</span>}
      </button>
      {open && (
        <div className="bell-panel" role="region" aria-label={tr("Notifications")}>
          {items.length === 0 && <p className="muted small">{tr("Nothing yet. Backups, shared albums and new movies show up here.")}</p>}
          <ul>
            {items.map((n) => {
              const inner = (<><strong>{tx(n.title)}</strong>{n.body && <span>{tx(n.body)}</span>}<time>{ago(n.created_at)}</time></>);
              return (
                <li key={n.id} className={n.read_at ? "" : "new"}>
                  {n.link ? <Link to={n.link} onClick={() => setOpen(false)}>{inner}</Link> : <div>{inner}</div>}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
