import { defineConfig, devices } from '@playwright/test';

// E2E against the Vite dev server with the API mocked per test (e2e/fixtures.ts). Screenshots of every screen state
// go to SCREENSHOT_DIR for the side-by-side review with the Figma frames (CLAUDE.md §0, docs/FIGMA_MAP.md).
const PORT = 5174;

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: `http://localhost:${PORT}`,
    locale: 'sk-SK',
    timezoneId: 'Europe/Bratislava',
    // Block SW by default so page.route API mocks are not bypassed by Workbox NetworkOnly.
    serviceWorkers: 'block',
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
    { name: 'mobile', use: { ...devices['Pixel 7'], viewport: { width: 390, height: 844 } }, grep: /@mobile/ },
  ],
  webServer: {
    // Preview (not `vite dev`) so the PWA service worker exists for @pwa tests that set
    // serviceWorkers: 'allow' and assert navigateFallbackDenylist.
    command: `npm run build && npx vite preview --host 127.0.0.1 --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
});
