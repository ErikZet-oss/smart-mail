/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react';
import { readFileSync } from 'node:fs';
import { defineConfig, type Plugin } from 'vite';
import { VitePWA } from 'vite-plugin-pwa';

const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8')) as { version: string };

/** Preview-only stubs so e2e can hit /api/version without a live backend (CI). */
function e2ePreviewApiStub(): Plugin {
  return {
    name: 'e2e-preview-api-stub',
    configurePreviewServer(server) {
      server.middlewares.use((req, res, next) => {
        const path = req.url?.split('?')[0] ?? '';
        if (path === '/api/version') {
          res.setHeader('content-type', 'application/json');
          res.end(JSON.stringify({ version: pkg.version, env: 'e2e' }));
          return;
        }
        if (path === '/healthz' || path === '/readyz') {
          res.setHeader('content-type', 'application/json');
          res.end(JSON.stringify({ status: 'ok' }));
          return;
        }
        next();
      });
    },
  };
}

// Dev server proxies the API to the backend (docker compose: app on :8000).
export default defineConfig({
  plugins: [
    react(),
    e2ePreviewApiStub(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.svg', 'apple-touch-icon.png', 'logo-smart.svg', 'logo-smart-white.svg'],
      manifest: {
        name: 'Smart Mail',
        short_name: 'Smart Mail',
        description: 'Firemný e-mailový klient Smart s.r.o.',
        lang: 'sk',
        start_url: '/',
        display: 'standalone',
        background_color: '#FFFFFF',
        theme_color: '#0F75BC',
        icons: [
          { src: '/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icon-512.png', sizes: '512x512', type: 'image/png' },
          { src: '/icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        navigateFallback: '/index.html',
        // Never serve the SPA shell for backend navigations (OIDC return, /api/docs, probes).
        navigateFallbackDenylist: [/^\/api\//, /^\/healthz/, /^\/readyz/],
        globPatterns: ['**/*.{js,css,html,svg,png,ico,woff2}'],
        runtimeCaching: [
          {
            urlPattern: ({ url }) => url.pathname.startsWith('/api/'),
            handler: 'NetworkOnly',
          },
        ],
      },
      devOptions: { enabled: false },
    }),
  ],
  define: { __APP_VERSION__: JSON.stringify(pkg.version) },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/healthz': 'http://localhost:8000',
      '/readyz': 'http://localhost:8000',
    },
  },
  preview: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/healthz': 'http://localhost:8000',
      '/readyz': 'http://localhost:8000',
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    exclude: ['e2e/**', 'node_modules/**', 'dist/**'],
  },
});
