// "Locks after [5] minutes without use": the vault's idle time, changeable per browser.
import { useEffect, useState } from "react";
import { t as tr } from "../i18n";
import { LOCK_MAX, LOCK_MIN, lockMinutes, setLockMinutes, useVaultKey } from "../vault/session";

export default function AutoLock() {
  useVaultKey();  // re-render when the setting changes
  const saved = lockMinutes();
  const [value, setValue] = useState(String(saved));
  useEffect(() => setValue(String(saved)), [saved]);
  const commit = () => {
    const n = Number(value);
    if (!Number.isFinite(n) || value.trim() === "") { setValue(String(saved)); return; }
    setLockMinutes(n);
    setValue(String(lockMinutes()));
  };
  return (
    <label className="autolock" title={tr("Saved on this browser only")}>
      {tr("Locks after")}
      <input type="number" inputMode="numeric" min={LOCK_MIN} max={LOCK_MAX} step={1} value={value}
        onChange={(e) => setValue(e.target.value)} onBlur={commit} onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
        aria-label={tr("Minutes without use before the vault locks")} />
      {tr("min without use")}
    </label>
  );
}
