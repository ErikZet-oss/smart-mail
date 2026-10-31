import type { Page } from '@playwright/test';

import { DEFAULT_PREFS, expect, foldersView, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

// Phase 3d — invoice_attach card, „Poslať“ in the Zákazník card, Settings 13b. Fictional data only.

const COMPANY = {
  money_id: '11111111-1111-4111-8111-111111111111',
  name: 'Fiktívna firma 01 s.r.o.',
  code: 'F0001',
  ico: '36123459',
  dic: null,
  icdph: 'SK2020000001',
  email: 'info@firma01.example',
  discount_pct: '5',
  due_days: 14,
};
const CARD = {
  company: COMPANY,
  receivables: {
    error: null,
    open_count: 2,
    open_total: '1234.5',
    overdue_count: 1,
    overdue_total: '1000',
    oldest_overdue_days: 40,
    mixed_currency: false,
    items: [
      {
        id: 'i1',
        kind: 'invoice',
        number: 'FV2600042',
        due_on: '2026-09-21',
        issued_on: '2026-09-07',
        total: '1000',
        remaining: '1000',
      },
    ],
  },
  orders: { error: 'money_unavailable', items: [] },
  deliveries: { error: null, items: [] },
  activities: { error: 'waiting_for_probe', items: [] },
  persons: [{ money_id: 'p1', name: 'Ján Fiktívny', function: 'nákup', email: 'jan@firma01.example', phone: null }],
};

async function setup(page: Page, extra: Parameters<typeof mockApi>[1]) {
  const view = foldersView();
  const inbox = view.folders.find((f) => f.special_use === 'inbox') ?? view.folders[0];
  if (!inbox) throw new Error('foldersView has no inbox');
  const row = {
    id: 'm1',
    thread_id: 't-m1',
    folder_id: inbox.id,
    uid: 1,
    subject: 'Kópia faktúry',
    from_name: 'Ján Fiktívny',
    from_email: 'jan@firma01.example',
    preview: 'Dobrý deň…',
    received_at: '2026-10-30T07:42:00Z',
    sent_at: '2026-10-30T07:42:00Z',
    size: 1200,
    seen: true,
    flagged: false,
    answered: false,
    has_attachments: false,
    thread_count: 1,
  };
  await mockApi(page, {
    'GET /api/auth/me': { body: ME },
    'GET /api/auth/persons': { body: ME_PICKER },
    'GET /api/system/info': { body: { admin_contact_email: null, features: { money: true } } },
    'GET /api/mail/mailboxes/default/folders': { body: view },
    [`GET /api/mail/mailboxes/default/folders/${inbox.id}/messages`]: {
      body: { mode: 'list', total: 1, page: 1, page_size: 50, messages: [row], threads: [], prefs: DEFAULT_PREFS.list },
    },
    'GET /api/mail/mailboxes/default/messages/m1': {
      body: {
        ...row,
        message_id: '<m1@example.test>',
        to: [{ name: null, email: 'pilot@smartmail.test' }],
        cc: [],
        body_text: 'Dobrý deň',
        body_html_sanitized: '<p>Dobrý deň</p>',
        attachments: [],
        auth_results: null,
        thread_status: 'open',
        snoozed_until: null,
        assignee_id: null,
        remote_images_offered: false,
        remote_images_mode: 'known',
      },
    },
    'PUT /api/mail/prefs': { body: DEFAULT_PREFS },
    'GET /api/money/messages/m1/customer': {
      body: { email: null, method: null, confidence: 0, needs_confirmation: false, company: null, candidates: [] },
    },
    ...extra,
  });
}

const INVOICE_CARD = {
  id: 's-inv',
  type: 'invoice_attach',
  status: 'pending',
  to: ['jan@firma01.example'],
  subject: '',
  body: 'Dobrý deň,\n\nv prílohe Vám posielame kópiu faktúry FV2600042.\n\nS pozdravom',
  language: 'sk',
  rationale: null,
  confidence: 0.95,
  checks: [
    { id: 'invoice_owner_ok', level: 'ok', params: { count: 1 } },
    { id: 'invoice_other_customer', level: 'warning', params: { number: 'FV2600099' } },
  ],
  blocked: false,
  invoices: [
    { id: 'i1', kind: 'invoice', number: 'FV2600042', due_on: '2026-09-21', total: '1000', remaining: '1000' },
  ],
  company_name: COMPANY.name,
};

test('3d invoice card: collapsed, then approve prepares the draft @mobile', async ({ page }, info) => {
  const approved: unknown[] = [];
  await setup(page, {
    'GET /api/mail/mailboxes/default/messages/m1/suggestions': { body: [INVOICE_CARD] },
    'POST /api/suggestions/s-inv/approve': (payload) => {
      approved.push(payload);
      return { body: { suggestion_id: 's-inv', draft_id: 'd-9', edited: false } };
    },
    'GET /api/mail/compose/d-9': { status: 404, body: { detail: { code: 'draft_not_found' } } },
    'GET /api/mail/mailboxes/default/identities': { body: [] },
    'GET /api/money/messages/m1/customer': {
      body: {
        email: 'jan@firma01.example',
        method: 'person',
        confidence: 0.98,
        needs_confirmation: false,
        company: COMPANY,
        candidates: [],
      },
    },
  });
  await page.goto('/mail/default/inbox/m1');
  const card = page.getByTestId('ai-invoice-card');
  await expect(card).toHaveAttribute('data-collapsed', 'true');
  await expect(card.getByRole('button', { name: 'Pripraviť koncept s faktúrou' })).toHaveCount(0);
  await card.getByRole('button', { expanded: false }).click();
  await expect(card).toContainText('FV2600042');
  await expect(card).toContainText('1 000,00 €');
  await expect(card).toContainText('Faktúra patrí firme príjemcu');
  await expect(card).toContainText('Faktúra FV2600099 patrí inej firme – do konceptu sa nepridá');
  await shot(page, `phase3d-card-${info.project.name}`);
  await card.getByRole('button', { name: 'Pripraviť koncept s faktúrou' }).click();
  await expect(page).toHaveURL(/\/compose\/d-9/);
  expect(approved).toEqual([{ body: null }]);
});

test('3d blocked approve explains the owner check', async ({ page }) => {
  await setup(page, {
    'GET /api/mail/mailboxes/default/messages/m1/suggestions': { body: [INVOICE_CARD] },
    'POST /api/suggestions/s-inv/approve': {
      status: 409,
      body: { detail: { code: 'suggestion_blocked', checks: [] } },
    },
  });
  await page.goto('/mail/default/inbox/m1');
  const card = page.getByTestId('ai-invoice-card');
  await card.getByRole('button', { expanded: false }).click();
  await card.getByRole('button', { name: 'Pripraviť koncept s faktúrou' }).click();
  await expect(page.getByText('Kontrola v Money zastavila prípravu', { exact: false })).toBeVisible();
  await expect(page).not.toHaveURL(/compose/);
});

test('3d „Poslať“ in the Zákazník card prepares a draft', async ({ page }) => {
  const sent: unknown[] = [];
  await setup(page, {
    'GET /api/money/messages/m1/customer': {
      body: {
        email: 'jan@firma01.example',
        method: 'person',
        confidence: 0.98,
        needs_confirmation: false,
        company: COMPANY,
        candidates: [],
      },
    },
    [`GET /api/money/companies/${COMPANY.money_id}/card`]: { body: CARD },
    'POST /api/money/messages/m1/invoice-draft': (payload) => {
      sent.push(payload);
      return { body: { draft_id: 'd-10' } };
    },
    'GET /api/mail/compose/d-10': { status: 404, body: { detail: { code: 'draft_not_found' } } },
    'GET /api/mail/mailboxes/default/identities': { body: [] },
  });
  await page.goto('/mail/default/inbox/m1?panel=customer');
  await page.getByRole('button', { name: 'Poslať faktúru FV2600042 zákazníkovi' }).click();
  await expect.poll(() => sent).toEqual([{ number: 'FV2600042' }]);
  await expect(page).toHaveURL(/\/compose\/d-10/);
});

test('3d Settings 13b: report ids, validation, save', async ({ page }) => {
  const saved: unknown[] = [];
  const ADMIN = { ...ME, person: { ...ME.person, role: 'admin' } };
  await mockApi(page, {
    'GET /api/auth/me': { body: ADMIN },
    'GET /api/auth/persons': { body: { ...ME_PICKER, persons: [ADMIN.person] } },
    'GET /api/settings/nav': {
      body: {
        sections: [
          {
            id: '13',
            path: 'money',
            title: 'Money S4',
            subs: [{ id: '13b', path: 'reports', title: 'Tlačové zostavy' }],
          },
        ],
        paths: { money: '13' },
      },
    },
    'GET /api/system/maintenance': { body: { active: false, until: null } },
    'GET /api/settings/money/reports': {
      body: { invoice: { sk: '12', en: '', de: '' }, proforma: { sk: '', en: '', de: '' } },
    },
    'PUT /api/settings/money/reports': (payload) => {
      saved.push(payload);
      return { body: payload };
    },
  });
  await page.goto('/settings/money/reports');
  const panel = page.getByTestId('settings-money-reports');
  await expect(panel.getByLabel('ID zostavy – Faktúra vydaná SK')).toHaveValue('12');
  await panel.getByLabel('ID zostavy – Faktúra vydaná EN').fill('12;x');
  await expect(panel.getByText('ID zostavy je GUID alebo číslo konfigurácie zostavy.')).toBeVisible();
  await expect(panel.getByRole('button', { name: 'Uložiť' })).toBeDisabled();
  await panel.getByLabel('ID zostavy – Faktúra vydaná EN').fill('14');
  await panel.getByRole('button', { name: 'Uložiť' }).click();
  await expect
    .poll(() => saved)
    .toEqual([{ invoice: { sk: '12', en: '14', de: '' }, proforma: { sk: '', en: '', de: '' } }]);
  await expect(panel).toContainText('originálne PDF z Money');
});
