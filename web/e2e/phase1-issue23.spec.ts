import type { Page } from '@playwright/test';

import { expect, ME, ME_PICKER, mockApi, test } from './fixtures';

const SIGNED_IN = { 'GET /api/auth/me': { body: ME }, 'GET /api/auth/persons': { body: ME_PICKER } };

type Draft = {
  id: string;
  mailbox_id: string;
  mode: string;
  identity_id: string;
  to_addrs: { email: string }[];
  cc_addrs: { email: string }[];
  bcc_addrs: { email: string }[];
  subject: string;
  body_html: string;
  body_text: string;
  include_signature: boolean;
  signature_html_override: null;
  signature_person_id: string;
  priority: string;
  request_mdn: boolean;
  request_dsn: boolean;
  save_sent: boolean;
  status: string;
  scheduled_at: null;
  undo_until: string | null;
  send_error: string | null;
  send_error_meta: null;
  attachments: [];
  checks: [];
  updated_at: string;
  sent_message_id?: string | null;
  sent_thread_id?: string | null;
  sent_folder_ref?: string | null;
};

function editingDraft(): Draft {
  return {
    id: 'd-23',
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
    updated_at: '2026-10-28T10:00:00Z',
  };
}

const IDENTITIES = {
  'GET /api/mail/mailboxes/default/identities': {
    body: [
      {
        id: 'id-1',
        display_name: 'Jana Testová',
        email: 'jana@smartmail.test',
        organization: 'Smart s.r.o.',
        is_default: true,
      },
    ],
  },
  'GET /api/mail/responses': { body: [] },
};

/** Opens W4/M4, waits for the new draft (the fields are disabled until it exists, #56), fills it and sends. */
async function openCompose(page: Page) {
  const created = page.waitForResponse((r) => r.url().endsWith('/api/mail/mailboxes/default/compose'));
  await page.goto('/compose?mailbox=default');
  await expect(page.getByTestId('compose-screen')).toBeVisible();
  await created;
  const toField = page.getByLabel('Komu');
  await expect(toField).toBeEnabled();
  await toField.fill('sender@smartmail.test');
  await expect(toField).toHaveValue('sender@smartmail.test');
  await page.getByLabel('Predmet').fill('Potvrdenie odoslania');
  // Footer send (the header control on a phone only opens the pre-send dialog).
  await page.getByRole('button', { name: 'Odoslať' }).last().click();
}

/**
 * Deterministic send mock (#56): before the send, `GET /compose/d-23` returns the editing draft; the first GET after
 * the send returns `queued`, every later GET returns `final` — independent of how often W4, M4 or the tracker poll.
 * Resolves `finalServed` once the first `final` payload has gone out.
 */
async function mockSendFlow(page: Page, final: Draft) {
  const draft = editingDraft();
  const queued: Draft = {
    ...draft,
    to_addrs: [{ email: 'sender@smartmail.test' }],
    subject: 'Potvrdenie odoslania',
    status: 'queued',
    undo_until: '2099-01-01T00:00:00Z',
    updated_at: '2026-10-28T10:00:02Z',
  };
  let sent = false;
  let getsAfterSend = 0;
  let served: () => void = () => undefined;
  const finalServed = new Promise<void>((resolve) => {
    served = resolve;
  });

  await mockApi(page, {
    ...SIGNED_IN,
    ...IDENTITIES,
    'POST /api/mail/mailboxes/default/compose': { body: draft },
    'PATCH /api/mail/compose/d-23': { body: queued },
  });
  await page.route('**/api/mail/compose/d-23/send', async (route) => {
    sent = true;
    await route.fulfill({ json: queued });
  });
  await page.route('**/api/mail/compose/d-23', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    if (!sent) return route.fulfill({ json: draft });
    getsAfterSend += 1;
    if (getsAfterSend === 1) return route.fulfill({ json: queued });
    await route.fulfill({ json: { ...queued, ...final } });
    served();
  });
  return { finalServed };
}

// Both tests run in both projects on purpose: the send controls differ (desktop footer / phone footer + app bar)
// and the toasts must work in both layouts.
test('send shows Odosiela sa… then Správa bola odoslaná. @mobile', async ({ page }) => {
  const { finalServed } = await mockSendFlow(page, {
    ...editingDraft(),
    to_addrs: [{ email: 'sender@smartmail.test' }],
    subject: 'Potvrdenie odoslania',
    status: 'sent',
    sent_message_id: 'm-sent',
    sent_thread_id: 'th-sent',
    sent_folder_ref: 'sent',
    updated_at: '2026-10-28T10:00:03Z',
  });

  await openCompose(page);
  await expect(page.getByText('Odosiela sa… Späť')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Späť' })).toBeVisible();
  await expect(page).toHaveURL(/\/mail\/default\/inbox/);
  await finalServed;
  const sentToast = page.getByRole('button', { name: 'Správa bola odoslaná.' });
  await expect(sentToast).toBeVisible();
  await sentToast.click();
  await expect(page).toHaveURL(/\/mail\/default\/sent\/th-sent/);
});

test('failed send shows the reason and Otvoriť koncept @mobile', async ({ page }) => {
  const { finalServed } = await mockSendFlow(page, {
    ...editingDraft(),
    to_addrs: [{ email: 'sender@smartmail.test' }],
    subject: 'Potvrdenie odoslania',
    status: 'failed',
    send_error: 'server_unavailable',
    updated_at: '2026-10-28T10:00:04Z',
  });

  await openCompose(page);
  await expect(page.getByText('Odosiela sa… Späť')).toBeVisible();
  await finalServed;
  const alert = page.getByRole('alert');
  await expect(alert).toContainText('Odoslanie zlyhalo – mailový server neodpovedá');
  await alert.getByRole('button', { name: 'Otvoriť koncept' }).click();
  await expect(page).toHaveURL(/\/compose\/d-23/);
});

test('#56 typing while the new draft is still being created is not overwritten @mobile', async ({ page }) => {
  // A slow `POST /compose` (CI runner): the fields stay disabled until the draft exists, so nothing typed is lost.
  await mockApi(page, {
    ...SIGNED_IN,
    ...IDENTITIES,
    'POST /api/mail/mailboxes/default/compose': { body: editingDraft(), delayMs: 1500 },
    'GET /api/mail/compose/d-23': { body: editingDraft() },
  });
  const loaded = page.waitForResponse((r) => r.url().endsWith('/api/mail/compose/d-23'));
  await page.goto('/compose?mailbox=default');
  const toField = page.getByLabel('Komu');
  await expect(toField).toBeDisabled();
  await toField.fill('sender@smartmail.test'); // waits until the field is enabled
  await loaded;
  await expect(toField).toHaveValue('sender@smartmail.test');
});
