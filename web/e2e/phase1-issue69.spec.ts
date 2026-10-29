import { expect, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

/** Issue #69: a refused send shows the SMTP server's own reply under the Slovak message (fictional data). */
const REPLY = 'SMTPSenderRefused:550:Sending mail from your country (de) is not allowed';

const failedDraft = (sendError: string) => ({
  id: 'd-69',
  mailbox_id: 'mb-1',
  mode: 'new',
  identity_id: 'id-1',
  to_addrs: [{ email: 'odberatel@example.test' }],
  cc_addrs: [],
  bcc_addrs: [],
  subject: 'Ponuka',
  body_html: '<p>Dobrý deň</p>',
  body_text: 'Dobrý deň',
  include_signature: true,
  signature_html_override: null,
  signature_person_id: 'p1',
  priority: 'normal',
  request_mdn: false,
  request_dsn: false,
  save_sent: true,
  status: 'failed',
  scheduled_at: null,
  undo_until: null,
  send_error: sendError,
  send_error_meta: { code: sendError.split(':')[0] },
  attachments: [],
  checks: [],
  updated_at: '2026-10-29T10:00:00Z',
});

async function open(page: import('@playwright/test').Page, sendError: string) {
  await mockApi(page, {
    'GET /api/auth/me': { body: ME },
    'GET /api/auth/persons': { body: ME_PICKER },
    'GET /api/mail/mailboxes/default/identities': {
      body: [{ id: 'id-1', display_name: 'Jana Testová', email: 'jana@smartmail.test', is_default: true }],
    },
    'GET /api/mail/responses': { body: [] },
    'GET /api/mail/compose/d-69': { body: failedDraft(sendError) },
  });
  await page.goto('/compose/d-69?mailbox=default');
  return page.getByTestId('compose-send-error');
}

test('#69 W4 refused send shows the server reply and the country hint @mobile', async ({ page }, info) => {
  const banner = await open(page, REPLY);
  await expect(banner).toContainText('Odoslanie zlyhalo – server odmietol príjemcu alebo správu.');
  await expect(banner).toContainText('Odpoveď servera: 550 Sending mail from your country (de) is not allowed');
  await expect(banner).toContainText('Povoľte odosielanie zo zahraničia v administrácii schránky.');
  await shot(page, `issue69-W4-server-reply-${info.project.name}`);
});

test('#69 W4 other send errors show no server reply @mobile', async ({ page }) => {
  const banner = await open(page, 'server_unavailable');
  await expect(banner).toContainText('mailový server neodpovedá');
  await expect(banner).not.toContainText('Odpoveď servera');
});
