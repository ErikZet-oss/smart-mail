import { DEFAULT_PREFS, expect, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

const SIGNED_IN = { 'GET /api/auth/me': { body: ME }, 'GET /api/auth/persons': { body: ME_PICKER } };

const draft = (id: string, extra: Record<string, unknown> = {}) => ({
  id,
  mailbox_id: 'mb1',
  mode: 'new',
  identity_id: 'id1',
  to_addrs: [] as { email: string; name?: string }[],
  cc_addrs: [] as unknown[],
  bcc_addrs: [] as unknown[],
  subject: '',
  body_html: '<p></p>',
  body_text: '',
  include_signature: true,
  signature_html_override: null,
  signature_person_id: null,
  priority: 'normal',
  request_mdn: false,
  request_dsn: false,
  save_sent: true,
  status: 'editing',
  scheduled_at: null,
  undo_until: null,
  send_error: null,
  attachments: [] as unknown[],
  checks: [] as unknown[],
  updated_at: new Date().toISOString(),
  ...extra,
});

test.describe('W4c / W4f compose schedule + popup', () => {
  test('W4c schedule dialog opens from send menu', async ({ page }) => {
    await mockApi(page, {
      ...SIGNED_IN,
      'POST /api/mail/mailboxes/default/compose': { body: draft('draft-w4c') },
      'GET /api/mail/compose/draft-w4c': { body: draft('draft-w4c', { subject: 'Test', body_html: '<p>ahoj</p>' }) },
      'PATCH /api/mail/compose/draft-w4c': { body: draft('draft-w4c', { subject: 'Test' }) },
      'GET /api/mail/mailboxes/default/identities': {
        body: [{ id: 'id1', display_name: 'Jana', email: 'jana@smartsro.sk', organization: null, is_default: true }],
      },
      'GET /api/mail/prefs': { body: DEFAULT_PREFS },
    });
    await page.goto('/compose?mailbox=default');
    await expect(page.getByTestId('compose-screen')).toBeVisible();
    await page.getByLabel('Ďalšie možnosti odoslania').click();
    await page.getByRole('menuitem', { name: 'Naplánovať' }).click();
    await expect(page.getByTestId('schedule-send-dialog')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Naplánovať odoslanie' })).toBeVisible();
    await shot(page, 'w4c-naplanovat-playwright');
    await page.screenshot({ path: '/opt/cursor/artifacts/screenshots/w4c-naplanovat-playwright.png', fullPage: true });
  });

  test('W4f popup mode chrome', async ({ page }) => {
    await mockApi(page, {
      ...SIGNED_IN,
      'GET /api/mail/compose/draft-w4f': {
        body: draft('draft-w4f', {
          subject: 'Re: Cenová ponuka',
          to_addrs: [{ email: 'peter@smartsro.sk', name: 'Peter' }],
          body_html: '<p>Dobrý deň</p>',
        }),
      },
      'GET /api/mail/mailboxes/default/identities': {
        body: [{ id: 'id1', display_name: 'Jana', email: 'jana@smartsro.sk', organization: null, is_default: true }],
      },
    });
    await page.setViewportSize({ width: 720, height: 640 });
    await page.goto('/compose/draft-w4f?mailbox=default&popup=1');
    await expect(page.getByTestId('compose-popup')).toBeVisible();
    await expect(page.getByLabel('Minimalizovať')).toBeVisible();
    await shot(page, 'w4f-okno-pisania-playwright');
    await page.screenshot({
      path: '/opt/cursor/artifacts/screenshots/w4f-okno-pisania-playwright.png',
      fullPage: true,
    });
  });
});
