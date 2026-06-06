import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

// API port is overridable so the dev server can proxy to a non-default backend.
// `opspilot serve --with-ui` sets this to match its --port; falls back to 8001
// (the serve default) for a bare `pnpm dev`.
const apiPort = process.env.OPSPILOT_API_PORT ?? '8001';

export default defineConfig({
  plugins: [sveltekit()],
  server: {
    proxy: {
      '/api': `http://localhost:${apiPort}`
    }
  }
});
