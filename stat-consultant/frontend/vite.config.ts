import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The app talks to the backend over same-origin relative URLs (see api.ts /
// useConsult.ts) because the bundled build is served by FastAPI itself. In dev
// the page is on Vite's port instead, so proxy the two backend prefixes rather
// than branching on import.meta.env.DEV in the client — one code path, and the
// production bundle carries no hardcoded port.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
    },
  },
})
