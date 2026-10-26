import { test as base, type Page, type Route } from '@playwright/test';

type Reply = { status?: number; body: unknown; delayMs?: number; never?: boolean };

export const ME = {
  account_id: 'a1',
  email: 'jana@smartsro.sk',
  kind: 'personal',
  branch: null,
  person: {
    id: 'p1',
    first_name: 'Jana',
    last_name: 'Testová',
    full_name: 'Jana Testová',
    role: 'sales',
    function: null,
    is_manager: false,
  },
  needs_person: false,
  read_only: false,
};

/** GET /api/auth/persons of the personal account ME (only itself, nothing to switch). */
export const ME_PICKER = {
  branch: null,
  email: ME.email,
  persons: [ME.person],
  current_person_id: ME.person.id,
  last_person_id: null,
  idle_ask_minutes: null,
};

let seq = 0;
const folder = (name: string, special: string | null, unread = 0, total = unread) => ({
  id: `f-${++seq}`,
  name,
  label: name,
  parent_id: null,
  depth: 0,
  special_use: special,
  unread,
  total,
  selectable: true,
});

/** Fictional folder column of the seeded test mailbox (tools/seed_test_imap.py, folders of the customer's Roundcube). */
export function foldersView(
  email = 'pilot@smartmail.test',
  quota = { used_kb: 819, limit_kb: 2048, percent: 40, level: 'normal' },
) {
  seq = 0;
  return {
    mailbox: { id: 'mb-1', email, unread: 12, sync_state: 'ok' },
    folders: [
      folder('INBOX', 'inbox', 12, 40),
      folder('Drafts', 'drafts', 0, 2),
      folder('Sent', 'sent', 0, 9),
      folder('Junk', 'junk', 4, 4),
      folder('Trash', 'trash', 1, 6),
      folder('Archív', null, 0, 12),
      folder('Dodávatelia', null, 39, 120),
      folder('Faktúry', null, 17, 300),
      folder('Kurier', null, 42, 80),
      folder('Nitra', null, 0, 14),
      folder('Senica', null, 6484, 7000),
      folder('Smart', null, 0, 0),
      folder('Trenčín', null, 3653, 4000),
    ],
    quota,
    sync: {
      state: 'ok',
      error: null as string | null,
      last_synced_at: '2026-10-26T08:00:00Z' as string | null,
    },
  };
}

export const MAIL_DEFAULTS: Record<string, Reply> = {
  'GET /api/mail/mailboxes': { body: [foldersView().mailbox] },
  'GET /api/mail/mailboxes/default/folders': { body: foldersView() },
};

/** Mock the API: "METHOD /path" → reply (or a function of the JSON body for stateful flows). The W2 folder column
 * answers with `MAIL_DEFAULTS` unless overridden; other unmocked API calls answer 401 (not signed in). */
export async function mockApi(page: Page, given: Record<string, Reply | ((body: unknown) => Reply)>) {
  const replies = { ...MAIL_DEFAULTS, ...given };
  await page.route('**/api/**', async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const key = `${request.method()} ${url.pathname}`;
    if (key === 'GET /api/auth/csrf') {
      await route.fulfill({ json: { ok: true }, headers: { 'set-cookie': 'sm_csrf=e2e-csrf; Path=/' } });
      return;
    }
    const given = replies[key];
    const reply =
      typeof given === 'function'
        ? given(request.postDataJSON() as unknown)
        : (given ?? { status: 401, body: { detail: { code: 'unauthenticated', reason: 'missing' } } });
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
