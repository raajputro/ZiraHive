import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/hind-siliguri/400.css";
import "@fontsource/hind-siliguri/500.css";
import "@fontsource/hind-siliguri/600.css";
import "./styles.css";
import App from "./App";
import { loadConfig } from "./api";

void loadConfig();
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
