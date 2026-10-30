import type { Page } from '@playwright/test';

import { DEFAULT_PREFS, expect, foldersView, ME, ME_PICKER, mockApi, test } from './fixtures';

// #143 W3 Viac › „Zmeniť kategóriu…“ and „Znova zaradiť (AI)“ (no Figma frame: Dialog + radio list).

const SIGNED_IN = { 'GET /api/auth/me': { body: ME }, 'GET /api/auth/persons': { body: ME_PICKER } };

const row = (id: string, folderId: string, subject: string) => ({
  id,
  thread_id: `t-${id}`,
  folder_id: folderId,
  uid: Number(id.slice(1)),
  subject,
  from_name: 'Ján Novák',
  from_email: 'novak@abcstav.example',
  preview: 'Dobrý deň…',
  received_at: '2026-10-26T07:42:00Z',
  sent_at: '2026-10-26T07:42:00Z',
  size: 1200,
  seen: true,
  flagged: false,
  answered: false,
  has_attachments: false,
  thread_count: 1,
});

const SUBJECTS: Record<string, string> = {
  m1: 'Kópia faktúry 2026123',
  m2: 'Cenová ponuka M10×30 A2',
  m3: 'Reklamácia',
};

async function setup(page: Page, extra: Parameters<typeof mockApi>[1] = {}) {
  const view = foldersView();
  const inbox = view.folders.find((f) => f.special_use === 'inbox') ?? view.folders[0];
  if (!inbox) throw new Error('foldersView has no inbox');
  const gone = new Set<string>();
  const bulkCalls: { action: string; message_ids: string[] }[] = [];
  const detail = (id: string) => ({
    ...row(id, inbox.id, SUBJECTS[id] ?? id),
    message_id: `<${id}@example.test>`,
    to: [{ name: null, email: 'pilot@smartmail.test' }],
    cc: [],
    body_text: `Text ${id}`,
    body_html_sanitized: `<p>Text ${id}</p>`,
    attachments: [],
    auth_results: null,
    thread_status: 'open',
    snoozed_until: null,
    assignee_id: null,
    remote_images_offered: false,
    remote_images_mode: 'known',
  });
  await mockApi(page, {
    ...SIGNED_IN,
    'GET /api/mail/mailboxes/default/folders': { body: view },
    [`GET /api/mail/mailboxes/default/folders/${inbox.id}/messages`]: () => {
      const messages = Object.keys(SUBJECTS)
        .filter((id) => !gone.has(id))
        .map((id) => row(id, inbox.id, SUBJECTS[id] ?? id));
      return {
        body: {
          mode: 'list',
          total: messages.length,
          page: 1,
          page_size: 50,
          messages,
          threads: [],
          prefs: DEFAULT_PREFS.list,
        },
      };
    },
    'GET /api/mail/mailboxes/default/messages/m1': { body: detail('m1') },
    'GET /api/mail/mailboxes/default/messages/m2': { body: detail('m2') },
    'GET /api/mail/mailboxes/default/messages/m3': { body: detail('m3') },
    'POST /api/mail/mailboxes/default/messages/bulk': (payload) => {
      const body = payload as { action: string; message_ids: string[] };
      bulkCalls.push(body);
      if (body.action === 'delete' || body.action === 'purge') body.message_ids.forEach((id) => gone.add(id));
      return { body: { ok: body.message_ids.length } };
    },
    'PUT /api/mail/prefs': { body: DEFAULT_PREFS },
    ...extra,
  });
  return { bulkCalls };
}

const option = (page: Page, subject: string) => page.getByRole('option').filter({ hasText: subject });

const CATEGORIES = {
  categories: [
    { id: 'invoice_request', label_sk: 'Žiadosti o faktúru', description_sk: '', color_token: 'info', count: 0 },
    { id: 'supplier_document', label_sk: 'Doklady dodávateľov', description_sk: '', color_token: 'danger', count: 0 },
  ],
};

test('#143 change the category by hand; AI reclassify explains a manual correction', async ({ page }) => {
  const changes: unknown[] = [];
  await setup(page, {
    'GET /api/mail/mailboxes/default/ai/categories': { body: CATEGORIES }, // ?all=1 — the mock key has no query
    'POST /api/mail/mailboxes/default/messages/m1/category': (payload) => {
      changes.push(payload);
      return { body: { message_id: 'm1', category: 'supplier_document', corrected: true, needs_reply: false } };
    },
    'POST /api/mail/mailboxes/default/messages/m1/reclassify': {
      status: 409,
      body: { detail: { code: 'category_corrected_manually' } },
    },
  });
  await page.goto('/mail/default/inbox');
  await option(page, 'Kópia faktúry 2026123').click();
  await page.getByRole('button', { name: 'Viac' }).first().click();
  await page.getByRole('menuitem', { name: 'Zmeniť kategóriu…' }).click();
  const dialog = page.getByRole('dialog', { name: 'Zmeniť kategóriu' });
  await dialog.getByRole('radio', { name: 'Doklady dodávateľov' }).check();
  await dialog.getByRole('button', { name: 'Uložiť' }).click();
  await expect(dialog).toHaveCount(0);
  await expect.poll(() => changes).toEqual([{ category: 'supplier_document' }]);
  await expect(page.getByText('Kategória zmenená.')).toBeVisible();

  await page.getByRole('button', { name: 'Viac' }).first().click();
  await page.getByRole('menuitem', { name: 'Znova zaradiť (AI)' }).click();
  await expect(page.getByText('Kategóriu zmenil človek – AI ju neprepíše.', { exact: false })).toBeVisible();
});
