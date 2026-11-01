import { DEFAULT_PREFS, expect, foldersView, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

// #89: Vymazať takes the row away at once (optimistic); the server answer only confirms or rolls back.

const SIGNED_IN = { 'GET /api/auth/me': { body: ME }, 'GET /api/auth/persons': { body: ME_PICKER } };

const row = (id: string, folderId: string, subject: string) => ({
  id,
  thread_id: `t-${id}`,
  folder_id: folderId,
  uid: 1,
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

async function setup(page: import('@playwright/test').Page, bulk: { status?: number; delayMs: number }) {
  const view = foldersView();
  const inbox = view.folders.find((f) => f.special_use === 'inbox') ?? view.folders[0];
  if (!inbox) throw new Error('foldersView has no inbox');
  let deleted = false;
  const detail = {
    ...row('m1', inbox.id, 'Kópia faktúry 2026123'),
    message_id: '<1@example.test>',
    to: [{ name: null, email: 'pilot@smartmail.test' }],
    cc: [],
    body_text: 'Text správy',
    body_html_sanitized: '<p>Text správy</p>',
    attachments: [],
    auth_results: null,
    thread_status: 'open',
    snoozed_until: null,
    assignee_id: null,
    remote_images_offered: false,
    remote_images_mode: 'known',
  };
  await mockApi(page, {
    ...SIGNED_IN,
    'GET /api/mail/mailboxes/default/folders': { body: view },
    [`GET /api/mail/mailboxes/default/folders/${inbox.id}/messages`]: () => ({
      body: {
        mode: 'list',
        total: deleted ? 1 : 2,
        page: 1,
        page_size: 50,
        messages: [
          ...(deleted ? [] : [row('m1', inbox.id, 'Kópia faktúry 2026123')]),
          row('m2', inbox.id, 'Cenová ponuka M10×30 A2'),
        ],
        threads: [],
        prefs: DEFAULT_PREFS.list,
      },
    }),
    'GET /api/mail/mailboxes/default/messages/m1': { body: detail },
    'POST /api/mail/mailboxes/default/messages/bulk': () => {
      if (!bulk.status || bulk.status < 400) deleted = true;
      return bulk.status && bulk.status >= 400
        ? { status: bulk.status, delayMs: bulk.delayMs, body: { detail: { code: 'mail_server_unavailable' } } }
        : { delayMs: bulk.delayMs, body: { ok: 1 } };
    },
    'PUT /api/mail/prefs': { body: DEFAULT_PREFS },
  });
}

const subject = (page: import('@playwright/test').Page) =>
  page.getByRole('option').filter({ hasText: 'Kópia faktúry 2026123' });

/** Desktop: the toolbar button; mobile (#185, M3 `83:2434`): Vymazať is in „Viac“. */
async function deleteOpen(page: import('@playwright/test').Page, mobile: boolean) {
  if (!mobile) {
    await page.getByRole('button', { name: 'Vymazať', exact: true }).first().click();
    return;
  }
  await page.getByTestId('m3-action-bar').getByRole('button', { name: 'Viac' }).click();
  await page.getByRole('menuitem', { name: 'Vymazať' }).click();
}

test.describe('#89 fast delete @mobile', () => {
  test('#89 delete removes the row before the server answers', async ({ page }, info) => {
    await setup(page, { delayMs: 3000 });
    await page.goto('/mail/default/inbox/t-m1');
    await expect(page.getByText('Text správy')).toBeVisible();
    const started = Date.now();
    await deleteOpen(page, info.project.name === 'mobile');
    if (info.project.name === 'mobile') await expect(page.getByText('Cenová ponuka M10×30 A2')).toBeVisible();
    await expect(subject(page)).toHaveCount(0, { timeout: 1000 });
    expect(Date.now() - started).toBeLessThan(1000); // the mocked server needs 3 s
    await expect(page.getByText('Správa je v Koši.')).toBeVisible({ timeout: 5000 });
    await expect(subject(page)).toHaveCount(0);
    await shot(page, `issue89-deleted-${info.project.name}`);
  });

  test('#89 failed delete brings the row back with an error toast', async ({ page }, info) => {
    await setup(page, { status: 503, delayMs: 800 });
    await page.goto('/mail/default/inbox/t-m1');
    await expect(page.getByText('Text správy')).toBeVisible();
    await deleteOpen(page, info.project.name === 'mobile');
    await expect(subject(page)).toHaveCount(0, { timeout: 500 });
    await expect(page.getByText('Akcia sa nepodarila – skúste to znova.')).toBeVisible({ timeout: 5000 });
    await expect(subject(page)).toHaveCount(1);
    await shot(page, `issue89-rollback-${info.project.name}`);
  });
});
