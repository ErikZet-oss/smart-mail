import AxeBuilder from '@axe-core/playwright';
import type { Page } from '@playwright/test';

import { DEFAULT_PREFS, expect, foldersView, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

// #222 — issued delivery note as Money's own print PDF: pick, „opravený“ warning, a branch without the report, the
// #215 tick for another company's note. Fictional data only.

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

const note = (
  number: string,
  issued: string,
  own: boolean,
  selected: boolean,
  extra: Record<string, unknown> = {},
) => ({
  id: `d-${number}`,
  kind: 'delivery_note',
  number,
  due_on: null,
  total: '88.4',
  remaining: '88.4',
  issued_on: issued,
  order: 'OR06024026',
  own,
  exact: selected,
  selected,
  owner_money_id: own ? null : 'c-other',
  owner_name: own ? null : 'Fiktívna Odberateľ s.r.o.',
  branch: 'Nitra',
  report_ok: true,
  ...extra,
});

const CARD = {
  id: 's-dl',
  type: 'delivery_note_attach',
  status: 'pending',
  to: ['jan@firma01.example'],
  subject: '',
  body: 'Dobrý deň,\n\nv prílohe Vám posielame dodací list DV260042 k objednávke č. OR06024026.\n\nS pozdravom',
  language: 'sk',
  rationale: null,
  confidence: 0.95,
  checks: [
    { id: 'delivery_note_corrected', level: 'warning', params: {} },
    { id: 'delivery_note_found_by_order', level: 'warning', params: { order: 'OR06024026' } },
  ],
  blocked: false,
  pick: true,
  invoices: [
    note('DV260042', '2026-11-17', true, true),
    note('DV260041', '2026-11-10', true, false, { branch: 'Senica', report_ok: false }),
    note('DV260040', '2026-11-05', false, false),
  ],
  company_name: 'Fiktívny Objednávateľ s.r.o.',
};

test('#222 delivery note card: corrected warning, no report row, foreign tick, approve picked @mobile', async ({
  page,
}, info) => {
  const approved: unknown[] = [];
  await setup(page, {
    'GET /api/mail/mailboxes/default/messages/m1/suggestions': { body: [CARD] },
    'POST /api/suggestions/s-dl/approve': (payload) => {
      approved.push(payload);
      return { body: { suggestion_id: 's-dl', draft_id: 'd-22', edited: false } };
    },
    'GET /api/mail/compose/d-22': { status: 404, body: { detail: { code: 'draft_not_found' } } },
    'GET /api/mail/mailboxes/default/identities': { body: [] },
  });
  await page.goto('/mail/default/inbox/m1');
  const card = page.getByTestId('ai-delivery-note-card');
  await expect(card).toContainText('Návrh: poslať dodací list z Money');
  await card.getByRole('button', { expanded: false }).click();
  await expect(card).toContainText(
    'Zákazník žiada opravu – najprv uprav dodací list v Money, PDF sa vytvorí z aktuálnych údajov.',
  );
  const rows = card.getByTestId('invoice-pick-row');
  await expect(rows.nth(0)).toContainText('dodací list · vystavený 17. 11. 2026');
  await expect(card.getByTestId('invoice-pick-DV260042')).toBeChecked();
  await expect(rows.nth(1)).toContainText('Pobočka Senica nemá nastavenú tlačovú zostavu dodacieho listu');
  await expect(card.getByTestId('invoice-pick-DV260041')).toBeDisabled();
  await expect(rows.nth(2)).toContainText('Dodací list je vystavený na Fiktívna Odberateľ s.r.o.');
  if (info.project.name === 'desktop') {
    const axe = await new AxeBuilder({ page })
      .include('[data-testid="ai-delivery-note-card"]')
      .withTags(['wcag2a', 'wcag2aa'])
      .analyze();
    expect(axe.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')).toEqual([]);
  }
  await shot(page, `issue222-delivery-note-${info.project.name}`);
  const approve = card.getByRole('button', { name: 'Pripraviť koncept s dodacím listom' });
  await card.getByTestId('invoice-pick-DV260042').uncheck();
  await card.getByTestId('invoice-pick-DV260040').check();
  const ack = card.getByTestId('invoice-ack');
  await expect(ack).toContainText(
    'Dodací list je vystavený na Fiktívna Odberateľ s.r.o., žiada Fiktívny Objednávateľ s.r.o.',
  );
  await expect(approve).toBeDisabled();
  await ack.getByLabel('Overil som, že odosielateľ smie dostať tento dodací list').check();
  await approve.click();
  await expect(page).toHaveURL(/\/compose\/d-22/);
  expect(approved).toEqual([{ body: null, acknowledged_checks: ['invoice_other_customer'], selected: ['DV260040'] }]);
});

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
const delivery = (id: string, number: string) => ({
  id,
  number,
  company_id: COMPANY.money_id,
  issued_on: '2026-11-17',
  moved_on: null,
  reference: null,
  state: 1,
  transport: 'Kuriér',
  total: '88.4',
});

test('#222 Zákazník: PDF icon only on delivery notes whose branch has the report', async ({ page }) => {
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
    [`GET /api/money/companies/${COMPANY.money_id}/card`]: {
      body: {
        company: COMPANY,
        receivables: {
          error: null,
          open_count: 0,
          open_total: '0',
          overdue_count: 0,
          overdue_total: '0',
          oldest_overdue_days: null,
          mixed_currency: false,
          items: [],
        },
        orders: { error: null, items: [] },
        deliveries: { error: null, items: [delivery('dl-1', 'DV260042'), delivery('dl-2', 'DV260043')] },
        activities: { error: null, items: [] },
        persons: [],
        delivery_pdf: ['dl-1'],
      },
    },
  });
  await page.goto('/mail/default/inbox/m1');
  await page.getByTestId('company-chip').click();
  const card = page.getByTestId('customer-card');
  const link = card.getByRole('link', { name: 'PDF dodacieho listu DV260042 z Money' });
  await expect(link).toHaveAttribute('href', `/api/money/companies/${COMPANY.money_id}/delivery-notes/dl-1/pdf`);
  await expect(card.getByTestId('delivery-pdf-dl-2')).toHaveCount(0);
});
