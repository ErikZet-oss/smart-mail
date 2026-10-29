import type { Page } from '@playwright/test';

import { expect, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

/** Issue #38: Telo / Celá správa also on the IMAP server (bodies of unopened messages are not indexed locally). */
const SIGNED_IN = { 'GET /api/auth/me': { body: ME }, 'GET /api/auth/persons': { body: ME_PICKER } };

const hit = (id: string, subject: string) => ({
  id,
  folder_id: 'f-1',
  mailbox_id: 'mb-1',
  subject,
  from_name: 'Eva Testovacia',
  from_email: 'eva@dodavatel.example',
  preview: null,
  received_at: '2026-10-28T09:00:00Z',
  rank: 0,
});
const result = (messages: ReturnType<typeof hit>[], server: string | null) => ({
  q: 'paletový',
  scope: 'all',
  fields: ['body'],
  total: messages.length,
  oldest_downloaded_at: '2024-03-15T10:00:00Z',
  messages,
  server_search: server,
});

/** Local answer at once; the `server=true` answer only after `release()` (so the in-between state is visible). */
async function mockSearch(page: Page, serverState: string, serverHits: ReturnType<typeof hit>[]) {
  let release: () => void = () => undefined;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await mockApi(page, { ...SIGNED_IN });
  await page.route('**/api/search?*', async (route) => {
    const server = new URL(route.request().url()).searchParams.get('server') === 'true';
    if (!server) return route.fulfill({ json: result([hit('m-2', 'Otvorená správa')], null) });
    await gate;
    await route.fulfill({ json: result([hit('m-1', 'Neotvorená zásielka'), ...serverHits], serverState) });
  });
  return { release };
}

test('#38 W10 body search shows local hits, then „Hľadá sa aj na serveri…“, then the server hits @mobile', async ({
  page,
}, info) => {
  const { release } = await mockSearch(page, 'ok', [hit('m-2', 'Otvorená správa')]);
  await page.goto('/search?q=paletov%C3%BD&field=body&scope=all');
  await expect(page.getByText('Otvorená správa')).toBeVisible();
  await expect(page.getByTestId('search-server')).toHaveText('Hľadá sa aj na serveri…');
  await shot(page, `issue38-W10-server-searching-${info.project.name}`);
  release();
  await expect(page.getByText('Neotvorená zásielka')).toBeVisible();
  await expect(page.getByText('Otvorená správa')).toBeVisible();
  await expect(page.getByTestId('search-server')).toHaveCount(0);
});

test('#38 W10 server timeout keeps the local hits and says so', async ({ page }) => {
  let calls = 0;
  await mockApi(page, { ...SIGNED_IN });
  await page.route('**/api/search?*', async (route) => {
    calls += 1;
    const server = new URL(route.request().url()).searchParams.get('server') === 'true';
    await route.fulfill({ json: result([hit('m-2', 'Otvorená správa')], server ? 'timeout' : null) });
  });
  await page.goto('/search?q=paletov%C3%BD&field=body&scope=all');
  await expect(page.getByTestId('search-server')).toContainText('Mailový server neodpovedal');
  await expect(page.getByText('Otvorená správa')).toBeVisible();
  expect(calls).toBe(2);
});

test('#38 W10 subject search never asks the server', async ({ page }) => {
  const asked: string[] = [];
  await mockApi(page, { ...SIGNED_IN });
  await page.route('**/api/search?*', async (route) => {
    asked.push(new URL(route.request().url()).searchParams.get('server') ?? 'local');
    await route.fulfill({ json: result([hit('m-2', 'Otvorená správa')], null) });
  });
  await page.goto('/search?q=paletov%C3%BD&field=subject&scope=all');
  await expect(page.getByText('Otvorená správa')).toBeVisible();
  expect(asked).toEqual(['local']);
});
