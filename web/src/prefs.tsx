import { createContext, useContext, useState, type ReactNode } from "react";

// Per-device settings, kept in this browser only.
interface Prefs { lowData: boolean; setLowData: (v: boolean) => void }
const PrefsContext = createContext<Prefs>({ lowData: false, setLowData: () => undefined });
export const usePrefs = () => useContext(PrefsContext);

const KEY = "zirahive:lowData";
function read(): boolean {
  try { return localStorage.getItem(KEY) === "1"; } catch { return false; }
}

export function PrefsProvider({ children }: { children: ReactNode }) {
  const [lowData, set] = useState(read);
  const setLowData = (v: boolean) => {
    set(v);
    try { localStorage.setItem(KEY, v ? "1" : "0"); } catch { /* private mode */ }
  };
  return <PrefsContext.Provider value={{ lowData, setLowData }}>{children}</PrefsContext.Provider>;
}
