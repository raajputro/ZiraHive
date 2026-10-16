import { useEffect, useState } from "react";
import { ChevronRight, Folder, HardDrive, ArrowUp } from "lucide-react";
import { api, ApiError, type FolderBrowse } from "../api";
import { t as tr, tx } from "../i18n";
import Dialog from "./Dialog";

/** Pick a folder on the PC's drives (as GharBox sees them). */
export default function FolderPicker({ onPick, onClose }: { onPick: (f: { path: string; label: string; name: string; guess: string | null }) => void; onClose: () => void }) {
  const [at, setAt] = useState<FolderBrowse | null>(null);
  const [error, setError] = useState("");
  const open = (path?: string) => { setError(""); api.browseFolders(path).then(setAt).catch((e) => setError(e instanceof ApiError ? e.message : tr("That didn't work"))); };
  useEffect(() => open(), []);
  return (
    <Dialog title={tr("Choose a folder")} onClose={onClose} wide>
      <div className="picker-head">
        <button className="icon" disabled={!at?.path} onClick={() => open(at?.parent ?? undefined)} aria-label={tr("Up one folder")}><ArrowUp size={18} /></button>
        <code>{at?.label ?? tr("This PC")}</code>
      </div>
      {error && <p className="error">{error}</p>}
      {at && at.folders.length === 0 && (
        <p className="muted">{at.path ? tr("No folders in here.") : tr("No drives are shared with GharBox yet. Run setup.ps1 again, or add DRIVE_D=D:/ (and so on) to .env, then restart GharBox.")}</p>
      )}
      <ul className="picker-list">
        {at?.folders.map((f) => (
          <li key={f.path}>
            <button onClick={() => open(f.path)}>
              {at.path ? <Folder size={18} aria-hidden /> : <HardDrive size={18} aria-hidden />}
              <span>{at.path ? f.name : tx(f.label)}</span><ChevronRight size={16} aria-hidden />
            </button>
          </li>
        ))}
      </ul>
      <div className="admin-row">
        <button className="primary" disabled={!at?.path}
          onClick={() => at?.path && onPick({ path: at.path, label: at.label ?? at.path, name: at.label?.split("\\").pop() || "", guess: at.guess })}>
          {tr("Use this folder")}</button>
        <button onClick={onClose}>{tr("Cancel")}</button>
      </div>
    </Dialog>
  );
}
