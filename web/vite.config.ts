/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// In dev mode the Vite server proxies to the API, so the browser only ever
// sees one origin and there is no CORS configuration anywhere (D7).
const apiTarget = process.env.VITE_API_PROXY_TARGET ?? 'http://localhost:8000';
const proxied = ['/api', '/healthz', '/readyz', '/version'];

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    proxy: Object.fromEntries(proxied.map((path) => [path, { target: apiTarget }])),
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
