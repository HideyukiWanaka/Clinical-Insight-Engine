import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Local-first Web app: dev server binds to 127.0.0.1 only (ADR-0005 —
// same rationale as the API in cie/api/main.py). Monaco is bundled from the
// local `monaco-editor` package (see src/monaco-setup.ts), never fetched from
// a CDN, so the offline_first invariant (prompts/redesign/README.md) holds.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: Number(process.env.VITE_PORT ?? 5173),
    strictPort: true,
  },
  preview: {
    host: "127.0.0.1",
    port: Number(process.env.VITE_PORT ?? 5173),
    strictPort: true,
  },
  // Monaco ships large language chunks; group them so the main bundle stays lean.
  build: {
    chunkSizeWarningLimit: 3000,
  },
});
