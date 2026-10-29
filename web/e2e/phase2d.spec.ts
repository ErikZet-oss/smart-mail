import type { Page } from '@playwright/test';

import { DEFAULT_PREFS, expect, foldersView, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

// Phase 2d — W4a compose AI panel / M17 sheet: proposals are a diff, „Použiť“ replaces only the person's text.

const SIGNED_IN = { 'GET /api/auth/me': { body: ME }, 'GET /api/auth/persons': { body: ME_PICKER } };

const DRAFT = {
  id: 'd-1',
  mailbox_id: 'mb-1',
  mode: 'reply',
  identity_id: 'id-1',
  to_addrs: [{ name: 'Ján Novák', email: 'novak@abcstav.example' }],
  cc_addrs: [],
  bcc_addrs: [],
  subject: 'Re: Dopyt M8',
  body_html:
    '<p>ahoj, posielam ponuku</p>' +
    '<blockquote data-sm-quote="1"><p>Koľko stoja skrutky M8?</p></blockquote>' +
    '<div data-sm-signature="1"><p>Jana Testová · Smart s.r.o.</p></div>',
  body_text: 'ahoj, posielam ponuku',
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

async function setup(page: Page, ai = true) {
  const view = foldersView();
  const calls: unknown[] = [];
  await mockApi(page, {
    ...SIGNED_IN,
    'GET /api/mail/mailboxes/default/folders': {
      body: { ...view, mailbox: { ...view.mailbox, ai_enabled: ai, ai_available: ai } },
    },
    'GET /api/mail/compose/d-1': { body: DRAFT },
    'PATCH /api/mail/compose/d-1': { body: DRAFT },
    'GET /api/mail/mailboxes/default/identities': {
      body: [{ id: 'id-1', display_name: 'Jana Testová', email: 'jana@smartmail.test', is_default: true }],
    },
    'GET /api/mail/responses': { body: [] },
    'GET /api/mail/compose/d-1/signature-preview': { body: { html: '<p>Jana Testová · Smart s.r.o.</p>' } },
    'POST /api/mail/compose/d-1/ai': (payload) => {
      calls.push(payload);
      return {
        body: {
          action: 'formal',
          text: 'Dobrý deň, posielame Vám ponuku.',
          language: 'sk',
          unanswered: [],
          placeholders: [],
        },
      };
    },
    'PUT /api/mail/prefs': { body: DEFAULT_PREFS },
  });
  return calls;
}

const editor = (page: Page) => page.locator('.ProseMirror').first();

test.describe('Phase 2d W4a / M17 @mobile', () => {
  test('2d Formálnejšie shows a diff; Použiť replaces only the person’s text', async ({ page }, info) => {
    const calls = await setup(page);
    await page.goto('/compose/d-1?mailbox=default');
    await expect(editor(page)).toContainText('ahoj, posielam ponuku');
    await page.getByRole('button', { name: 'AI pri písaní' }).click();
    const panel = page.getByTestId('compose-ai-panel').last();
    await panel.getByRole('button', { name: 'Formálnejšie' }).click();
    const proposal = page.getByTestId('compose-ai-proposal');
    await expect(proposal.locator('del')).toContainText('ahoj, posielam');
    await expect(proposal.locator('ins')).toContainText('Dobrý deň, posielame Vám');
    await shot(page, `phase2d-W4a-diff-${info.project.name}`);
    expect(calls).toEqual([{ action: 'formal', text: 'ahoj, posielam ponuku' }]);
    await proposal.getByRole('button', { name: 'Použiť' }).click();
    await expect(editor(page)).toContainText('Dobrý deň, posielame Vám ponuku.');
    await expect(editor(page)).not.toContainText('ahoj, posielam ponuku');
    await expect(editor(page)).toContainText('Koľko stoja skrutky M8?');
    await expect(editor(page)).toContainText('Jana Testová · Smart s.r.o.');
  });

  test('2d Zahodiť keeps the text', async ({ page }) => {
    await setup(page);
    await page.goto('/compose/d-1?mailbox=default');
    await expect(editor(page)).toContainText('ahoj, posielam ponuku');
    await page.getByRole('button', { name: 'AI pri písaní' }).click();
    await page.getByTestId('compose-ai-panel').last().getByRole('button', { name: 'Formálnejšie' }).click();
    await page.getByTestId('compose-ai-proposal').getByRole('button', { name: 'Zahodiť' }).click();
    await expect(page.getByTestId('compose-ai-proposal')).toHaveCount(0);
    await expect(editor(page)).toContainText('ahoj, posielam ponuku');
  });

  test('2d no AI button when AI is off for the mailbox', async ({ page }) => {
    await setup(page, false);
    await page.goto('/compose/d-1?mailbox=default');
    await expect(editor(page)).toContainText('ahoj, posielam ponuku');
    await expect(page.getByRole('button', { name: 'AI pri písaní' })).toHaveCount(0);
  });
});
