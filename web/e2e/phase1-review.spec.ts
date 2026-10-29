import AxeBuilder from '@axe-core/playwright';
import type { Page } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';

import { DEFAULT_PREFS, expect, foldersView, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

/** #81 Phase 1 close-out: every Phase 1 screen of docs/FIGMA_MAP.md once, desktop + mobile — a screenshot for the
 * Figma review package (docs/phase1-review.md) and an axe run (WCAG 2 A/AA). Fictional data only. The axe findings
 * are written to test-results/axe/<screen>-<project>.json; serious/critical ones fail the test unless listed in
 * KNOWN (each with its follow-up issue). */
const ADMIN = { ...ME, person: { ...ME.person, role: 'admin' } };

const NAV_ADMIN = {
  sections: [
    {
      id: '01',
      path: 'preferences',
      title: 'Nastavenia',
      subs: [
        { id: '01a', path: 'ui', title: 'Používateľské rozhranie' },
        { id: '01b', path: 'mailbox-view', title: 'Zobrazenie schránky' },
        { id: '01c', path: 'reading', title: 'Zobrazovanie správ' },
        { id: '01d', path: 'composing', title: 'Vytváranie správ' },
        { id: '01e', path: 'shortcuts', title: 'Klávesové skratky' },
      ],
    },
    { id: '02', path: 'folders', title: 'Priečinky', subs: [] },
    {
      id: '03',
      path: 'identity',
      title: 'Identity a Môj profil',
      subs: [
        { id: '03a', path: 'list', title: 'Identity' },
        { id: '03b', path: 'profile', title: 'Môj profil' },
      ],
    },
    { id: '04', path: 'responses', title: 'Odpovede', subs: [] },
    { id: '05', path: 'filters', title: 'Filtre', subs: [] },
    { id: '06', path: 'vacation', title: 'Mimo kancelárie', subs: [] },
    { id: '07', path: 'ai', title: 'AI asistent', subs: [] },
    { id: '09', path: 'security', title: 'Bezpečnosť', subs: [] },
    { id: '09b', path: 'provider', title: 'Nastavenia e-mail schránky', subs: [] },
    { id: '10', path: 'users', title: 'Používatelia a role', subs: [] },
    {
      id: '11',
      path: 'branches',
      title: 'Pobočky a osoby',
      subs: [
        { id: '11a', path: 'details', title: 'Údaje' },
        { id: '11b', path: 'people', title: 'Osoby' },
        { id: '11c', path: 'signature', title: 'Podpis' },
        { id: '11d', path: 'login', title: 'Prihlasovanie' },
        { id: '11e', path: 'money', title: 'Money' },
      ],
    },
    { id: '12', path: 'mailboxes', title: 'Schránky', subs: [] },
  ],
};

/** serious/critical axe rules that are known and filed as issues (rule id → issue). */
const KNOWN: Record<string, string> = {
  // Avatar initials (aria-hidden) on Figma avatar tones — #83.
  'color-contrast@W9': '#83',
};

const view = foldersView();
const found = view.folders.find((f) => f.special_use === 'inbox') ?? view.folders[0];
if (!found) throw new Error('fixture has no folders');
const inbox = found;
const LIST = {
  mode: 'list' as const,
  total: 2,
  page: 1,
  page_size: 50,
  messages: [
    {
      id: 'm-1',
      thread_id: 't-1',
      folder_id: inbox.id,
      uid: 1,
      subject: 'Kópia faktúry 2026123',
      from_name: 'Ján Novák',
      from_email: 'novak@abcstav.example',
      preview: 'Dobrý deň, prosím o zaslanie kópie faktúry…',
      received_at: '2026-10-26T07:42:00Z',
      sent_at: '2026-10-26T07:42:00Z',
      size: 1200,
      seen: false,
      flagged: false,
      answered: false,
      has_attachments: true,
      thread_count: 1,
    },
    {
      id: 'm-2',
      thread_id: 't-2',
      folder_id: inbox.id,
      uid: 2,
      subject: 'Cenová ponuka M10×30 A2',
      from_name: 'Petra Kováčová',
      from_email: 'petra@example.test',
      preview: 'Posielam ponuku na skrutky…',
      received_at: '2026-10-26T06:10:00Z',
      sent_at: '2026-10-26T06:10:00Z',
      size: 800,
      seen: true,
      flagged: false,
      answered: false,
      has_attachments: false,
      thread_count: 1,
    },
  ],
  threads: [] as unknown[],
  prefs: DEFAULT_PREFS.list,
};
const DETAIL = {
  id: 'm-1',
  thread_id: 't-1',
  folder_id: inbox.id,
  uid: 1,
  message_id: '<1@example.test>',
  subject: 'Kópia faktúry 2026123',
  from_name: 'Ján Novák',
  from_email: 'novak@abcstav.example',
  to: [{ name: null, email: 'jana@smartmail.test' }],
  cc: [],
  sent_at: '2026-10-26T07:42:00Z',
  received_at: '2026-10-26T07:42:00Z',
  size: 1200,
  seen: true,
  flagged: false,
  answered: false,
  body_text: 'Dobrý deň,\nprosím o zaslanie kópie faktúry 2026123.\n',
  body_html_sanitized: '<p>Dobrý deň,</p><p>prosím o zaslanie kópie faktúry 2026123.</p>',
  attachments: [],
  auth_results: null,
  thread_status: 'open',
  snoozed_until: null,
  assignee_id: null,
};
const DRAFT = {
  id: 'd-1',
  mailbox_id: 'mb-1',
  mode: 'new',
  identity_id: 'id-1',
  to_addrs: [],
  cc_addrs: [],
  bcc_addrs: [],
  subject: '',
  body_html: '<p></p>',
  body_text: '',
  include_signature: true,
  signature_html_override: null,
  signature_person_id: 'p1',
  priority: 'normal',
  request_mdn: false,
  request_dsn: false,
  save_sent: true,
  status: 'editing',
  scheduled_at: null,
  undo_until: null,
  send_error: null,
  send_error_meta: null,
  attachments: [],
  checks: [],
  updated_at: '2026-10-26T12:00:00Z',
};

const SIGNED_IN = {
  'GET /api/auth/me': { body: ADMIN },
  'GET /api/auth/persons': { body: { ...ME_PICKER, persons: [ADMIN.person] } },
  'GET /api/settings/nav': { body: NAV_ADMIN },
  [`GET /api/mail/mailboxes/default/folders/${inbox.id}/messages`]: { body: LIST },
  'GET /api/mail/mailboxes/default/messages/m-1': { body: DETAIL },
  'POST /api/mail/mailboxes/default/compose': { body: DRAFT },
  'GET /api/mail/compose/d-1': { body: DRAFT },
  'PATCH /api/mail/compose/d-1': { body: DRAFT },
  'GET /api/mail/mailboxes/default/identities': {
    body: [{ id: 'id-1', display_name: 'Jana Testová', email: 'jana@smartmail.test', is_default: true }],
  },
  'GET /api/mail/responses': { body: [] },
  'GET /api/system/maintenance': { body: { active: false, until: null } },
  'GET /api/settings/preferences': {
    body: {
      ui: { theme: 'system', classic: false },
      list: { density: 'compact', mode: 'list', page_size: 50, show_ai_summary: true },
      reading: {},
      composing: { undo_send_seconds: 10 },
      shortcuts: {},
    },
  },
  'GET /api/settings/responses': {
    body: [{ id: 'r-1', name: 'Poďakovanie', text: 'Ďakujeme za objednávku.', shared: false, shortcut: null }],
  },
  'GET /api/settings/security/sessions': {
    body: [{ id: 's-1', device_id: 'Chrome · Windows', last_seen_at: '2026-10-29 10:00', current: true }],
  },
  'GET /api/settings/mailboxes/default/filters': {
    body: {
      script_name: 'roundcube',
      has_backup: true,
      mailbox_scope: 'personal',
      rules: [
        {
          id: 'f1',
          name: 'Dodávatelia Acme',
          enabled: true,
          match: 'anyof',
          editable: true,
          raw: '',
          conditions: [{ field: 'from', op: 'contains', value: '@acme-parts.test' }],
          actions: [{ type: 'fileinto', value: 'Dodávatelia' }],
        },
      ],
    },
  },
  'GET /api/settings/mailboxes/default/vacation': {
    body: {
      enabled: false,
      subject: 'Mimo kancelárie: {predmet}',
      body_sk: 'Som mimo kancelárie.',
      body_en: 'Out of office.',
      body_de: 'Außer Haus.',
      days: 7,
      start: null,
      end: null,
      has_backup: true,
      script_name: 'roundcube',
    },
  },
  'GET /api/settings/mailboxes/default/identities': {
    body: [
      {
        id: 'id-1',
        mailbox_id: 'mb-1',
        display_name: 'Jana Testová',
        email: 'jana@smartmail.test',
        organization: 'Smart s.r.o.',
        reply_to: null,
        bcc: [],
        is_default: true,
        signature_html: { sk: '<p><strong>Jana Testová</strong><br/>Smart s.r.o.</p>' },
        signature_images: [],
      },
    ],
  },
  'GET /api/settings/mailboxes/default/provider': {
    body: { email: 'jana@smartmail.test', imap_host: 'imap-test', imap_port: 993, provider_admin_url: null },
  },
  'GET /api/settings/admin/users': {
    body: [
      {
        id: 'a-1',
        email: 'jana@smartmail.test',
        kind: 'personal',
        active: true,
        last_login_at: null,
        branch_id: null,
        branch_name: null,
        persons_count: null,
        require_2fa: false,
        totp_enabled: false,
        person: { id: 'p1', first_name: 'Jana', last_name: 'Testová', role: 'admin', active: true },
      },
    ],
  },
  'GET /api/settings/admin/branches': {
    body: [
      {
        id: 'b-senica',
        name: 'Pobočka Senica',
        address: 'Hlavná 1, 905 01 Senica',
        phone: '+421 900 000 000',
        hours: 'Po–Pi 7:00–15:30',
        mailbox_id: 'mb-1',
        mailbox_email: 'senica@smartmail.test',
        login_account: null,
        idle_ask_minutes: null,
        remember_days: 30,
        logo_url: null,
        folder_ids: [],
        signature_template_html: { sk: '<p>{meno} {priezvisko}</p>' },
        signature_images: [],
        people: [
          {
            id: 'p-jana',
            first_name: 'Jana',
            last_name: 'Nováková',
            function: 'obchod',
            role: 'sales',
            is_manager: true,
            active: true,
            phone: null,
            mobile: '+421 900 000 010',
            personal_email: null,
            photo_url: null,
            cover_branch_ids: [],
          },
        ],
      },
    ],
  },
};

type Screen = {
  id: string;
  path: string;
  signedIn?: boolean;
  ready: (page: Page) => Promise<void>;
  mocks?: Parameters<typeof mockApi>[1];
  /** Opens an overlay screen (panel/dialog) after the page loaded. */
  open?: (page: Page, mobile: boolean) => Promise<void>;
  desktopOnly?: boolean;
};

const openAbout = async (p: Page, mobile: boolean) => {
  if (mobile) {
    await p.getByRole('button', { name: 'Viac' }).click();
    await p.getByTestId('screen-m18').getByRole('button', { name: 'O systéme' }).click();
  } else {
    await p.getByRole('button', { name: 'O systéme' }).click();
  }
};

const SHELL_MOCKS = {
  'GET /api/notifications': {
    body: {
      items: [
        {
          id: 'assign:t-1:1761501600',
          kind: 'assigned',
          created_at: '2026-10-26T18:00:00Z',
          unread: true,
          href: '/mail/default/inbox/t-1',
          params: { subject: 'Objednávka PO-1' },
        },
      ],
      unread_count: 1,
    },
  },
  'GET /api/settings/mailboxes/default/provider': {
    body: {
      email: ME.email,
      imap_host: 'mail.test',
      imap_port: 993,
      provider_admin_url: 'https://provider.test/admin',
    },
  },
};

const settings = (id: string, path: string): Screen => ({
  id,
  path: `/settings/${path}`,
  ready: async (page) => {
    await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible();
    await page.waitForLoadState('networkidle');
  },
});

const SCREENS: Screen[] = [
  {
    id: 'W1',
    path: '/login',
    signedIn: false,
    ready: (p) => expect(p.getByRole('button', { name: 'PRIHLÁSIŤ' })).toBeVisible(),
  },
  {
    id: 'W1c',
    path: '/login?reason=password-changed',
    signedIn: false,
    ready: (p) => expect(p.getByRole('button', { name: 'PRIHLÁSIŤ' })).toBeVisible(),
  },
  {
    id: 'W1a',
    path: '/login/2fa',
    signedIn: false,
    ready: (p) => expect(p.getByRole('heading', { level: 1 })).toBeVisible(),
  },
  { id: 'W1b', path: '/who', ready: (p) => expect(p.getByRole('heading', { level: 1 })).toBeVisible() },
  {
    id: 'W2',
    path: '/mail/default/inbox',
    ready: (p) => expect(p.getByText('Kópia faktúry 2026123').first()).toBeVisible(),
  },
  {
    id: 'W2c',
    path: '/mail/default/inbox/t-1',
    ready: (p) => expect(p.getByText('prosím o zaslanie kópie faktúry 2026123.').first()).toBeVisible(),
  },
  {
    id: 'W9',
    path: '/contacts/personal',
    mocks: {
      'GET /api/contacts/books': {
        body: [
          { id: 'book-personal', kind: 'personal', name: 'Osobné adresy' },
          { id: 'book-shared', kind: 'shared', name: 'Zdieľané' },
        ],
      },
      'GET /api/contacts/books/book-personal/contacts': {
        body: [
          {
            id: 'c1',
            address_book_id: 'book-personal',
            display_name: 'Ján Novák',
            first_name: 'Ján',
            last_name: 'Novák',
            organization: 'ABC Stav s.r.o.',
            notes: '',
            emails: [{ email: 'jan.novak@smartmail.test', type: 'work' }],
            phones: [],
            group_ids: [],
          },
        ],
      },
      'GET /api/contacts/books/book-personal/groups': { body: [] },
    },
    ready: (p) => expect(p.getByText('Ján Novák').first()).toBeVisible(),
  },
  { id: 'W4', path: '/compose', ready: (p) => expect(p.getByTestId('compose-screen')).toBeVisible() },
  settings('W12-01a', 'preferences/ui'),
  settings('W12-01b', 'preferences/mailbox-view'),
  settings('W12-01c', 'preferences/reading'),
  settings('W12-01d', 'preferences/composing'),
  settings('W12-01e', 'preferences/shortcuts'),
  settings('W12-02', 'folders'),
  settings('W12-03a', 'identity/list'),
  settings('W12-03b', 'identity/profile'),
  settings('W12-04', 'responses'),
  settings('W12-05', 'filters'),
  settings('W12-06', 'vacation'),
  settings('W12-09', 'security'),
  settings('W12-09b', 'provider'),
  settings('W12-10', 'users'),
  settings('W12-11a', 'branches/details'),
  settings('W12-11b', 'branches/people'),
  settings('W12-11c', 'branches/signature'),
  settings('W12-11d', 'branches/login'),
  settings('W12-12', 'mailboxes'),
  {
    id: 'W13',
    path: '/mail/default/inbox',
    mocks: SHELL_MOCKS,
    open: async (p, mobile) => {
      await openAbout(p, mobile);
      await p.getByRole('button', { name: 'Spustiť úvodnú prehliadku' }).click();
    },
    ready: (p) => expect(p.getByTestId(/^screen-(m-)?w13$/)).toBeVisible(),
  },
  {
    id: 'W14',
    path: '/mail/default/inbox',
    mocks: SHELL_MOCKS,
    open: async (p, mobile) => {
      if (mobile) {
        await p.getByRole('button', { name: 'Viac' }).click();
        await p.getByRole('button', { name: 'Notifikácie' }).click();
      } else {
        await p.getByRole('button', { name: /Notifikácie/ }).click();
      }
    },
    ready: (p) => expect(p.getByText('Objednávka PO-1')).toBeVisible(),
  },
  {
    id: 'W15',
    path: '/mail/default/inbox',
    mocks: SHELL_MOCKS,
    desktopOnly: true,
    open: async (p) => {
      await p.getByRole('navigation', { name: 'Hlavná navigácia' }).click();
      await p.keyboard.press('?');
    },
    ready: (p) => expect(p.getByTestId('screen-w15')).toBeVisible(),
  },
  {
    id: 'W15b',
    path: '/mail/default/inbox',
    mocks: SHELL_MOCKS,
    open: openAbout,
    ready: (p) => expect(p.getByTestId('screen-w15b')).toBeVisible(),
  },
  { id: 'W16a', path: '/403', ready: (p) => expect(p.getByRole('heading', { level: 1 })).toBeVisible() },
  { id: 'W16b', path: '/404', ready: (p) => expect(p.getByRole('heading', { level: 1 })).toBeVisible() },
  { id: 'W16c', path: '/500?ref=7F3A21C9', ready: (p) => expect(p.getByRole('heading', { level: 1 })).toBeVisible() },
  {
    id: 'W17',
    path: '/maintenance',
    signedIn: false,
    ready: (p) => expect(p.getByRole('heading', { level: 1 })).toBeVisible(),
  },
];

const results: Record<string, unknown> = {};

for (const screen of SCREENS) {
  test(`#81 review ${screen.id} @mobile`, async ({ page }, info) => {
    await mockApi(page, {
      'GET /api/system/maintenance': { body: { active: false, until: null } },
      ...(screen.signedIn === false ? {} : SIGNED_IN),
      ...(screen.mocks ?? {}),
    });
    const mobile = info.project.name === 'mobile';
    test.skip(mobile && screen.desktopOnly === true, 'keyboard-only screen');
    await page.goto(screen.path);
    if (screen.open) await screen.open(page, mobile);
    await screen.ready(page);
    await shot(page, `review-${screen.id}-${info.project.name}`);
    const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze();
    const serious = axe.violations
      .filter((v) => v.impact === 'serious' || v.impact === 'critical')
      .map((v) => ({
        id: v.id,
        impact: v.impact,
        help: v.help,
        nodes: v.nodes.map((n) => n.target.join(' ')).slice(0, 5),
      }));
    mkdirSync('test-results/axe', { recursive: true });
    writeFileSync(`test-results/axe/${screen.id}-${info.project.name}.json`, JSON.stringify(serious, null, 2));
    results[`${screen.id}-${info.project.name}`] = serious;
    expect(
      serious.filter((v) => !KNOWN[`${v.id}@${screen.id}`]),
      JSON.stringify(serious, null, 2),
    ).toEqual([]);
  });
}
