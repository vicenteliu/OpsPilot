import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

// API port is overridable so the dev server can proxy to a non-default backend
// (e.g. when port 8000 is taken). `opspilot serve --with-ui` sets this to match
// its --port; falls back to 8000 for a bare `pnpm dev`.
const apiPort = process.env.OPSPILOT_API_PORT ?? '8000';

export default defineConfig({
  plugins: [sveltekit()],
  server: {
    proxy: {
      '/api': `http://localhost:${apiPort}`
    }
  }
});
