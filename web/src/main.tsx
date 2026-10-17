import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/hind-siliguri/400.css";
import "@fontsource/hind-siliguri/500.css";
import "@fontsource/hind-siliguri/600.css";
import "./styles.css";
import App from "./App";
import { loadConfig } from "./api";

// ZiraHive was called GharBox: carry this browser's saved settings (low-data mode, reading
// positions, ...) over to the new names, once.
try {
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (key?.startsWith("gharbox")) {
      const renamed = "zirahive" + key.slice("gharbox".length);
      if (localStorage.getItem(renamed) === null) localStorage.setItem(renamed, localStorage.getItem(key) ?? "");
    }
  }
} catch { /* storage blocked: nothing to carry over */ }

void loadConfig();
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
