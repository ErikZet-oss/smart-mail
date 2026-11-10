import type { Page } from '@playwright/test';

import { DEFAULT_PREFS, expect, foldersView, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

// #215 (ADR-019) — another company's invoice: red row, required tick, then approve with the ack. Fictional data only.

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

const FOREIGN_CARD = {
  id: 's-foreign',
  type: 'invoice_attach',
  status: 'pending',
  to: ['jan@firma01.example'],
  subject: '',
  body: 'Dobrý deň,\n\nv prílohe Vám posielame kópiu faktúry FV2600099 k objednávke č. 2410000099.\n\nS pozdravom',
  language: 'sk',
  rationale: null,
  confidence: 0.95,
  checks: [
    {
      id: 'invoice_other_customer',
      level: 'requires_ack',
      params: { owner: 'Fiktívna Odberateľ s.r.o.', requester: 'Fiktívny Objednávateľ s.r.o.', numbers: ['FV2600099'] },
    },
    { id: 'invoice_found_by_order', level: 'warning', params: { order: '2410000099' } },
  ],
  blocked: false,
  invoices: [
    { id: 'i9', kind: 'invoice', number: 'FV2600099', due_on: '2026-09-21', total: '120.5', remaining: '120.5' },
  ],
  company_name: 'Fiktívny Objednávateľ s.r.o.',
};

test('#215 ack: red row, the tick unlocks approve, approve sends the ack @mobile', async ({ page }, info) => {
  const approved: unknown[] = [];
  await setup(page, {
    'GET /api/mail/mailboxes/default/messages/m1/suggestions': { body: [FOREIGN_CARD] },
    'POST /api/suggestions/s-foreign/approve': (payload) => {
      approved.push(payload);
      return { body: { suggestion_id: 's-foreign', draft_id: 'd-15', edited: false } };
    },
    'GET /api/mail/compose/d-15': { status: 404, body: { detail: { code: 'draft_not_found' } } },
    'GET /api/mail/mailboxes/default/identities': { body: [] },
  });
  await page.goto('/mail/default/inbox/m1');
  const card = page.getByTestId('ai-invoice-card');
  await card.getByRole('button', { expanded: false }).click();
  const ack = card.getByTestId('invoice-ack');
  await expect(ack).toContainText(
    'Faktúra je vystavená na Fiktívna Odberateľ s.r.o., žiada Fiktívny Objednávateľ s.r.o.',
  );
  const approve = card.getByRole('button', { name: 'Pripraviť koncept s faktúrou' });
  await expect(approve).toBeDisabled();
  await shot(page, `issue215-ack-${info.project.name}`);
  await ack.getByLabel('Overil som, že odosielateľ smie dostať túto faktúru').check();
  await expect(approve).toBeEnabled();
  await approve.click();
  await expect(page).toHaveURL(/\/compose\/d-15/);
  expect(approved).toEqual([{ body: null, acknowledged_checks: ['invoice_other_customer'] }]);
});
