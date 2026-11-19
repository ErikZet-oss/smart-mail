import type { Page } from '@playwright/test';

import { DEFAULT_PREFS, expect, foldersView, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

// #217 — invoices found by the customer's order number: pick up to 5, one company per draft, #215 tick for another
// company's invoice. Fictional data only.

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

const inv = (number: string, issued: string, own: boolean, selected: boolean, owner: string | null = null) => ({
  id: `i-${number}`,
  kind: 'invoice',
  number,
  due_on: '2026-11-20',
  total: '120.5',
  remaining: '120.5',
  issued_on: issued,
  order: 'OR06024026',
  own,
  exact: selected,
  selected,
  owner_money_id: own ? null : 'c-other',
  owner_name: owner,
});

const PICK_CARD = {
  id: 's-pick',
  type: 'invoice_attach',
  status: 'pending',
  to: ['jan@firma01.example'],
  subject: '',
  body: 'Dobrý deň,\n\nv prílohe Vám posielame kópiu faktúry FV2600301 k objednávke č. OR06024026.\n\nS pozdravom',
  language: 'sk',
  rationale: null,
  confidence: 0.95,
  checks: [{ id: 'invoice_found_by_order', level: 'warning', params: { order: 'OR06024026' } }],
  blocked: false,
  pick: true,
  invoices: [
    inv('FV2600301', '2026-10-31', true, true),
    inv('FV2600302', '2026-10-20', true, false),
    inv('FV2600303', '2026-10-10', false, false, 'Fiktívna Odberateľ s.r.o.'),
  ],
  company_name: 'Fiktívny Objednávateľ s.r.o.',
};

test('#217 pick: pre-selected own invoice, mixed choice blocked, foreign needs the tick @mobile', async ({
  page,
}, info) => {
  const approved: unknown[] = [];
  await setup(page, {
    'GET /api/mail/mailboxes/default/messages/m1/suggestions': { body: [PICK_CARD] },
    'POST /api/suggestions/s-pick/approve': (payload) => {
      approved.push(payload);
      return { body: { suggestion_id: 's-pick', draft_id: 'd-17', edited: false } };
    },
    'GET /api/mail/compose/d-17': { status: 404, body: { detail: { code: 'draft_not_found' } } },
    'GET /api/mail/mailboxes/default/identities': { body: [] },
  });
  await page.goto('/mail/default/inbox/m1');
  const card = page.getByTestId('ai-invoice-card');
  await card.getByRole('button', { expanded: false }).click();
  const rows = card.getByTestId('invoice-pick-row');
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(0)).toContainText('vystavená 31. 10. 2026');
  await expect(card.getByTestId('invoice-pick-FV2600301')).toBeChecked();
  await expect(card.getByTestId('invoice-pick-FV2600302')).not.toBeChecked();
  await expect(rows.nth(2)).toContainText('Faktúra je vystavená na Fiktívna Odberateľ s.r.o.');
  const approve = card.getByRole('button', { name: 'Pripraviť koncept s faktúrou' });
  await expect(approve).toBeEnabled();
  await shot(page, `issue217-pick-${info.project.name}`);

  await card.getByTestId('invoice-pick-FV2600303').check();
  await expect(card).toContainText('Jeden koncept môže obsahovať faktúry iba jednej firmy');
  await expect(approve).toBeDisabled();
  await card.getByTestId('invoice-pick-FV2600301').uncheck();
  const ack = card.getByTestId('invoice-ack');
  await expect(ack).toContainText(
    'Faktúra je vystavená na Fiktívna Odberateľ s.r.o., žiada Fiktívny Objednávateľ s.r.o.',
  );
  await expect(approve).toBeDisabled();
  await expect(card).toContainText('Text konceptu sa pri príprave upraví podľa vybraných faktúr.');
  await ack.getByLabel('Overil som, že odosielateľ smie dostať túto faktúru').check();
  await approve.click();
  await expect(page).toHaveURL(/\/compose\/d-17/);
  expect(approved).toEqual([{ body: null, acknowledged_checks: ['invoice_other_customer'], selected: ['FV2600303'] }]);
});

test('#217 pick: nothing ticked → approve disabled; own pick sends only the picked numbers', async ({ page }) => {
  const approved: unknown[] = [];
  await setup(page, {
    'GET /api/mail/mailboxes/default/messages/m1/suggestions': { body: [PICK_CARD] },
    'POST /api/suggestions/s-pick/approve': (payload) => {
      approved.push(payload);
      return { body: { suggestion_id: 's-pick', draft_id: 'd-18', edited: false } };
    },
    'GET /api/mail/compose/d-18': { status: 404, body: { detail: { code: 'draft_not_found' } } },
    'GET /api/mail/mailboxes/default/identities': { body: [] },
  });
  await page.goto('/mail/default/inbox/m1');
  const card = page.getByTestId('ai-invoice-card');
  await card.getByRole('button', { expanded: false }).click();
  const approve = card.getByRole('button', { name: 'Pripraviť koncept s faktúrou' });
  await card.getByTestId('invoice-pick-FV2600301').uncheck();
  await expect(card).toContainText('Vyberte aspoň jednu faktúru.');
  await expect(approve).toBeDisabled();
  await card.getByTestId('invoice-pick-FV2600302').check();
  await approve.click();
  await expect(page).toHaveURL(/\/compose\/d-18/);
  expect(approved).toEqual([{ body: null, selected: ['FV2600302'] }]);
});
