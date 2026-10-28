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

async function openCompose(page: Page) {
  await page.goto('/compose?mailbox=default');
  await expect(page.getByTestId('compose-screen')).toBeVisible();
  const toField = page.getByLabel('Komu');
  await expect(toField).toBeVisible();
  await toField.fill('sender@smartmail.test');
  await expect(toField).toHaveValue('sender@smartmail.test');
  await page.getByLabel('Predmet').fill('Potvrdenie odoslania');
  // Footer send (the header control on a phone only opens the pre-send dialog).
  await page.getByRole('button', { name: 'Odoslať' }).last().click();
}

test('send shows Odosiela sa… then Správa bola odoslaná. @mobile', async ({ page }) => {
  const draft = editingDraft();
  let phase: 'edit' | 'queued' | 'sent' = 'edit';
  let sawQueued = false;
  const queued: Draft = {
    ...draft,
    to_addrs: [{ email: 'sender@smartmail.test' }],
    subject: 'Potvrdenie odoslania',
    status: 'queued',
    undo_until: '2099-01-01T00:00:00Z',
    updated_at: '2026-10-28T10:00:02Z',
  };
  const sent: Draft = {
    ...queued,
    status: 'sent',
    undo_until: null,
    sent_message_id: 'm-sent',
    sent_thread_id: 'th-sent',
    sent_folder_ref: 'sent',
    updated_at: '2026-10-28T10:00:03Z',
  };

  await mockApi(page, {
    ...SIGNED_IN,
    ...IDENTITIES,
    'POST /api/mail/mailboxes/default/compose': { body: draft },
    'PATCH /api/mail/compose/d-23': { body: queued },
  });
  await page.route('**/api/mail/compose/d-23/send', async (route) => {
    phase = 'queued';
    await route.fulfill({ json: queued });
  });
  await page.route('**/api/mail/compose/d-23', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() !== 'GET' || !path.endsWith('/compose/d-23')) return route.fallback();
    if (phase === 'queued' && !sawQueued) {
      sawQueued = true;
      await route.fulfill({ json: queued });
      return;
    }
    if (phase === 'queued' || phase === 'sent') {
      phase = 'sent';
      await route.fulfill({ json: sent });
      return;
    }
    await route.fulfill({ json: draft });
  });

  await openCompose(page);
  await expect(page.getByText('Odosiela sa… Späť')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Späť' })).toBeVisible();
  await expect(page).toHaveURL(/\/mail\/default\/inbox/);
  await expect(page.getByRole('button', { name: 'Správa bola odoslaná.' })).toBeVisible();
  await page.getByRole('button', { name: 'Správa bola odoslaná.' }).click();
  await expect(page).toHaveURL(/\/mail\/default\/sent\/th-sent/);
});

test('failed send shows the reason and Otvoriť koncept @mobile', async ({ page }) => {
  const draft = editingDraft();
  let phase: 'edit' | 'queued' | 'failed' = 'edit';
  let sawQueued = false;
  const queued: Draft = {
    ...draft,
    to_addrs: [{ email: 'sender@smartmail.test' }],
    subject: 'Potvrdenie odoslania',
    status: 'queued',
    undo_until: '2099-01-01T00:00:00Z',
    updated_at: '2026-10-28T10:00:02Z',
  };
  const failed: Draft = {
    ...queued,
    status: 'failed',
    undo_until: null,
    send_error: 'server_unavailable',
    updated_at: '2026-10-28T10:00:04Z',
  };

  await mockApi(page, {
    ...SIGNED_IN,
    ...IDENTITIES,
    'POST /api/mail/mailboxes/default/compose': { body: draft },
    'PATCH /api/mail/compose/d-23': { body: queued },
  });
  await page.route('**/api/mail/compose/d-23/send', async (route) => {
    phase = 'queued';
    await route.fulfill({ json: queued });
  });
  await page.route('**/api/mail/compose/d-23', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() !== 'GET' || !path.endsWith('/compose/d-23')) return route.fallback();
    if (phase === 'queued' && !sawQueued) {
      sawQueued = true;
      await route.fulfill({ json: queued });
      return;
    }
    if (phase === 'queued' || phase === 'failed') {
      phase = 'failed';
      await route.fulfill({ json: failed });
      return;
    }
    await route.fulfill({ json: draft });
  });

  await openCompose(page);
  await expect(page.getByText('Odosiela sa… Späť')).toBeVisible();
  const alert = page.getByRole('alert');
  await expect(alert).toContainText('Odoslanie zlyhalo – mailový server neodpovedá');
  await alert.getByRole('button', { name: 'Otvoriť koncept' }).click();
  await expect(page).toHaveURL(/\/compose\/d-23/);
});
