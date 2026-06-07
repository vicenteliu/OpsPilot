import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

// `process` is a Node global available when Vite loads this config; declared
// locally so svelte-check passes without pulling in @types/node.
declare const process: { env: Record<string, string | undefined> };

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
