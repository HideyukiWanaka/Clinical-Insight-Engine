import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// Side-effect import: point @monaco-editor/react at the local monaco bundle
// (offline_first) before any editor mounts.
import "./monaco-setup";
import App from "./App";
import "./styles.css";

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("#root element not found");

createRoot(rootEl).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
