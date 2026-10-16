import { useEffect, useRef, type ReactNode } from "react";
import { X } from "lucide-react";

/** A modal built on the native <dialog>: focus trapping, Esc to close and backdrop for free. */
export default function Dialog({ title, onClose, children, wide = false }:
  { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (d && !d.open) d.showModal();
    return () => d?.close();
  }, []);
  return (
    <dialog ref={ref} className={`dialog ${wide ? "wide" : ""}`} onCancel={(e) => { e.preventDefault(); onClose(); }}
      onClick={(e) => { if (e.target === ref.current) onClose(); }} aria-label={title}>
      <div className="dialog-body">
        <header className="dialog-head">
          <h2>{title}</h2>
          <button className="icon" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </header>
        {children}
      </div>
    </dialog>
  );
}
