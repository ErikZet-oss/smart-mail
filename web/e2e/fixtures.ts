import { test as base, type Page, type Route } from '@playwright/test';

type Reply = { status?: number; body: unknown; delayMs?: number; never?: boolean };

export const ME = {
  account_id: 'a1',
  email: 'jana@smartsro.sk',
  kind: 'personal',
  branch: null,
  person: { id: 'p1', first_name: 'Jana', last_name: 'Testová', full_name: 'Jana Testová', role: 'sales' },
  needs_person: false,
  read_only: false,
};

/** Mock the API: "METHOD /path" → reply. Unmocked API calls answer 401 (not signed in). */
export async function mockApi(page: Page, replies: Record<string, Reply>) {
  await page.route('**/api/**', async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const key = `${request.method()} ${url.pathname}`;
    if (key === 'GET /api/auth/csrf') {
      await route.fulfill({ json: { ok: true }, headers: { 'set-cookie': 'sm_csrf=e2e-csrf; Path=/' } });
      return;
    }
    const reply = replies[key] ?? { status: 401, body: { detail: { code: 'unauthenticated', reason: 'missing' } } };
    if (reply.never) return; // keeps the request pending (submitting state)
    if (reply.delayMs) await new Promise((r) => setTimeout(r, reply.delayMs));
    await route.fulfill({ status: reply.status ?? 200, json: reply.body });
  });
}

export const shotDir = process.env.SCREENSHOT_DIR ?? 'test-results/screens';

export async function shot(page: Page, name: string) {
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: `${shotDir}/${name}.png` });
}

export const test = base;
export { expect } from '@playwright/test';
