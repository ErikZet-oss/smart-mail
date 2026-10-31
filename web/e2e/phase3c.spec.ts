import type { Page } from '@playwright/test';

import { DEFAULT_PREFS, expect, foldersView, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

// Phase 3c — W3b Zákazník panel / M10 (FEATURE_MONEY). All companies, numbers and amounts are fictional.

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
    ...extra,
  });
}

test('3c Zákazník: card with KPIs, one part down, contacts @mobile', async ({ page }, info) => {
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
  });
  await page.goto('/mail/default/inbox/m1');
  await page.getByRole('button', { name: 'Zákazník' }).click();
  await expect(page).toHaveURL(/panel=customer/);
  const panel = page.getByTestId('customer-panel');
  await expect(panel.getByTestId('match-method')).toHaveText('jan@firma01.example – kontaktná osoba v Money');
  const card = panel.getByTestId('customer-card');
  await expect(card.getByRole('heading', { name: 'Fiktívna firma 01 s.r.o.' })).toBeVisible();
  await expect(card).toContainText('IČO 36123459 · IČ DPH SK2020000001 · F0001');
  await expect(card).toContainText('zľava 5 % · splatnosť 14 dní');
  await expect(card).toContainText('1 234,50 €');
  await expect(card).toContainText('najstaršia 40 dní');
  await expect(card).toContainText('FV2600042');
  await expect(card).toContainText('Money je teraz nedostupné.');
  await expect(card).toContainText('Zatiaľ nedostupné – čaká sa na test prepojenia s Money.');
  await expect(card).toContainText('Ján Fiktívny');
  await shot(page, `phase3c-customer-${info.project.name}`);
  await panel.getByRole('button', { name: 'Zavrieť panel Zákazník' }).click();
  await expect(panel).toHaveCount(0);
  await expect(page).not.toHaveURL(/panel=customer/);
});

test('3c not matched: search the cache and assign the address', async ({ page }, info) => {
  const links: unknown[] = [];
  let linked = false;
  await setup(page, {
    'GET /api/money/messages/m1/customer': () => ({
      body: linked
        ? {
            email: 'jan@firma01.example',
            method: 'confirmed',
            confidence: 1,
            needs_confirmation: false,
            company: COMPANY,
            candidates: [],
          }
        : {
            email: 'jan@firma01.example',
            method: null,
            confidence: 0,
            needs_confirmation: false,
            company: null,
            candidates: [],
          },
    }),
    'GET /api/money/companies/search': { body: [COMPANY] },
    'POST /api/money/links': (payload) => {
      links.push(payload);
      linked = true;
      return {
        body: {
          email: 'jan@firma01.example',
          method: 'confirmed',
          confidence: 1,
          needs_confirmation: false,
          company: COMPANY,
          candidates: [],
        },
      };
    },
    [`GET /api/money/companies/${COMPANY.money_id}/card`]: { body: CARD },
  });
  await page.goto('/mail/default/inbox/m1?panel=customer');
  const panel = page.getByTestId('customer-panel');
  await expect(panel.getByTestId('customer-not-matched')).toContainText(
    'Odosielateľa jan@firma01.example sme v Money nenašli.',
  );
  await expect(panel.getByRole('button', { name: 'Založiť firmu v Money' })).toBeDisabled();
  await panel.getByLabel('Priradiť k firme').fill('fiktívna');
  await panel.getByRole('button', { name: 'Priradiť k firme Fiktívna firma 01 s.r.o.' }).click();
  await expect.poll(() => links).toEqual([{ email: 'jan@firma01.example', company_money_id: COMPANY.money_id }]);
  await expect(panel.getByTestId('match-method')).toHaveText('jan@firma01.example – priradené ručne');
  await shot(page, `phase3c-assigned-${info.project.name}`);
});

test('3c Zákazník button is hidden without FEATURE_MONEY', async ({ page }) => {
  await setup(page, { 'GET /api/system/info': { body: { admin_contact_email: null, features: { money: false } } } });
  await page.goto('/mail/default/inbox/m1?panel=customer');
  await expect(page.getByRole('heading', { name: 'Kópia faktúry' }).first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Zákazník' })).toHaveCount(0);
  await expect(page.getByTestId('customer-panel')).toHaveCount(0);
});
