import { test as base, type Page, type Route } from '@playwright/test';

type Reply = { status?: number; body: unknown; delayMs?: number; never?: boolean };
type ReplySource = Reply | Promise<Reply> | ((body: unknown) => Reply | Promise<Reply>);

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
    mailbox: {
      id: 'mb-1',
      email,
      unread: 12,
      sync_state: 'ok',
      ai_enabled: false,
      ai_available: false,
    },
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

export const DEFAULT_PREFS = {
  list: {
    sort: 'date_received',
    sort_dir: 'desc',
    mode: 'list',
    density: 'compact',
    page_size: 50,
    show_ai_summary: true,
    mark_read: 'delay3',
    after_delete: 'next',
  },
  ui: { theme: 'light', classic: false, remote_images: 'known', prefer_html: true },
};

/** Empty list payload so W2 1d message fetches do not 401 the session when a test only mocks folders. */
export function emptyMessagesList() {
  return {
    mode: 'list' as const,
    total: 0,
    page: 1,
    page_size: 50,
    messages: [] as unknown[],
    threads: [] as unknown[],
    prefs: DEFAULT_PREFS.list,
  };
}

/** Empty AI triage — Phase 1 shells must not 401 on the 2b categories poll. Override in phase2b. */
export const EMPTY_AI_CATEGORIES = { categories: [] as unknown[] };

export const MAIL_DEFAULTS: Record<string, Reply> = {
  'GET /api/mail/mailboxes': { body: [foldersView().mailbox] },
  'GET /api/mail/mailboxes/default/folders': { body: foldersView() },
  'GET /api/mail/prefs': { body: DEFAULT_PREFS },
  'PUT /api/mail/prefs': { body: DEFAULT_PREFS },
  'GET /api/mail/mailboxes/default/ai/categories': { body: EMPTY_AI_CATEGORIES },
  // Rail polls notifications; unmocked 401 would kick the shell to login.
  'GET /api/notifications': { body: { items: [], unread_count: 0 } },
  'GET /api/system/info': { body: { admin_contact_email: null, features: { money: false } } },
};

/** Phase 1f W12: nav + profile so opening Nastavenia from older e2e shells does not 401 → /login. */
export const SETTINGS_DEFAULTS: Record<string, Reply> = {
  // W12-07 „Môj štýl písania“ (Phase 2e): off unless a test sets it
  'GET /api/settings/ai/style-profile': { body: { opt_in: false, text: '', generated_at: null, source_count: 0 } },
  'GET /api/settings/nav': {
    body: {
      sections: [
        {
          id: '03',
          path: 'identity',
          title: 'Identity',
          subs: [{ id: '03b', path: 'profile', title: 'Môj profil' }],
        },
      ],
    },
  },
  'GET /api/settings/mailboxes/default/signature-context': {
    body: {
      mailbox_kind: 'personal',
      account_kind: 'personal',
      branch_managed: false,
      preview_html: '',
      branch_id: null,
    },
  },
  'GET /api/settings/profile': {
    body: {
      id: ME.person.id,
      first_name: ME.person.first_name,
      last_name: ME.person.last_name,
      function: null,
      phone: null,
      mobile: null,
      personal_email: null,
      languages: ['sk'],
      style_guide: null,
      role: ME.person.role,
      signature_preview_html: '<p>Jana</p>',
    },
  },
  // Settings 10/11 (#33) load these on open; an unmocked call answers 401 and logs the shell out mid-test (#62).
  'GET /api/settings/admin/mailboxes': { body: [] },
  'GET /api/settings/admin/users': { body: [] },
  'GET /api/settings/admin/personal-people': { body: [] },
  'GET /api/settings/admin/branch-folders': { body: [] },
  'GET /api/settings/security/2fa': {
    body: { available: true, enabled: false, required: false, backup_codes_left: 0 },
  },
  // Branch signature (11c) loads presets on open. An unmocked 401 logs the shell out.
  'GET /api/settings/signature-presets': {
    body: {
      karta: { sk: '<p>{meno}</p>', cs: '<p>{meno}</p>', en: '<p>{meno}</p>', de: '<p>{meno}</p>' },
      text: { sk: '<p>S pozdravom</p>', cs: '<p>{meno}</p>', en: '<p>{meno}</p>', de: '<p>{meno}</p>' },
    },
  },
};

const FOLDER_MESSAGES = /^GET \/api\/mail\/mailboxes\/[^/]+\/folders\/[^/]+\/messages$/;
const MESSAGE_DETAIL = /^GET \/api\/mail\/mailboxes\/[^/]+\/messages\/[^/]+$/;
const MAILBOX_FOLDERS = /^GET \/api\/mail\/mailboxes\/[^/]+\/folders$/;
const AI_CATEGORIES = /^GET \/api\/mail\/mailboxes\/[^/]+\/ai\/categories$/;
const AI_SUGGESTIONS = /^GET \/api\/mail\/mailboxes\/[^/]+\/messages\/[^/]+\/suggestions$/;
const USER_ACCESS = /^GET \/api\/settings\/admin\/users\/[^/]+\/mailbox-access$/;

/** Mock the API: "METHOD /path" → reply (or a function of the JSON body for stateful flows). The W2 folder column
 * answers with `MAIL_DEFAULTS` unless overridden; other unmocked API calls answer 401 (not signed in). */
export async function mockApi(page: Page, given: Record<string, ReplySource>) {
  const replies = { ...MAIL_DEFAULTS, ...SETTINGS_DEFAULTS, ...given };
  await page.route('**/api/**', async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const key = `${request.method()} ${url.pathname}`;
    if (key === 'GET /api/auth/csrf') {
      await route.fulfill({ json: { ok: true }, headers: { 'set-cookie': 'sm_csrf=e2e-csrf; Path=/' } });
      return;
    }
    const entry = replies[key];
    let payload: unknown = null;
    if (typeof entry === 'function' && request.method() !== 'GET' && request.method() !== 'HEAD') {
      try {
        payload = request.postDataJSON();
      } catch {
        payload = null;
      }
    }
    let reply: Reply | undefined = await (typeof entry === 'function' ? entry(payload) : entry);
    // Phase 1d: list/detail prefs must not 401 a signed-in shell when a test only stubs folders
    if (!reply && FOLDER_MESSAGES.test(key)) {
      reply = { body: emptyMessagesList() };
    } else if (!reply && MESSAGE_DETAIL.test(key)) {
      reply = { status: 404, body: { detail: { code: 'message_not_found' } } };
    } else if (!reply && MAILBOX_FOLDERS.test(key)) {
      // deep-link mailboxes (e.g. nitra) share the seeded folder column unless overridden
      reply = { body: foldersView() };
    } else if (!reply && USER_ACCESS.test(key)) {
      // Settings 10 detail loads the mailbox access of the selected login (#55)
      reply = { body: [] };
    } else if (!reply && AI_SUGGESTIONS.test(key)) {
      // Phase 2c reading-pane cards — none unless a test gives some (#94)
      reply = { body: [] };
    } else if (!reply && AI_CATEGORIES.test(key)) {
      // Phase 2b poll — empty triage so Phase 1 shells stay signed in
      reply = { body: EMPTY_AI_CATEGORIES };
    } else if (!reply) {
      // Unmocked: answer 401 like the real API without a session — this logs the shell out, so say which call (#62).
      console.warn(`[mockApi] unmocked ${key} → 401 (the page will go to /login)`);
      reply = { status: 401, body: { detail: { code: 'unauthenticated', reason: 'missing' } } };
    }
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
