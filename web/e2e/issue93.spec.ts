import type { Page } from '@playwright/test';

import { DEFAULT_PREFS, expect, foldersView, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

// #93 UX_SPEC §6 list shortcuts (desktop: keyboard).

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

async function setup(page: Page) {
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
  });
  return { bulkCalls };
}

const option = (page: Page, subject: string) => page.getByRole('option').filter({ hasText: subject });

test.describe('#93 list shortcuts', () => {
  test('#93 Delete removes the open message', async ({ page }) => {
    const { bulkCalls } = await setup(page);
    await page.goto('/mail/default/inbox');
    await option(page, 'Kópia faktúry 2026123').click();
    await expect(page.getByText('Text m1')).toBeVisible();
    await page.keyboard.press('Delete');
    await expect(option(page, 'Kópia faktúry 2026123')).toHaveCount(0, { timeout: 1000 });
    await expect(page.getByText('Správa je v Koši.')).toBeVisible();
    expect(bulkCalls).toEqual([{ action: 'delete', message_ids: ['m1'] }]);
    await shot(page, 'issue93-delete');
  });

  test('#93 ArrowDown opens the next message, ArrowUp goes back', async ({ page }) => {
    await setup(page);
    await page.goto('/mail/default/inbox');
    await option(page, 'Kópia faktúry 2026123').click();
    await expect(page.getByText('Text m1')).toBeVisible();
    await page.keyboard.press('ArrowDown');
    await expect(page.getByText('Text m2')).toBeVisible();
    await expect(option(page, 'Cenová ponuka M10×30 A2')).toHaveAttribute('aria-selected', 'true');
    await page.keyboard.press('ArrowUp');
    await expect(page.getByText('Text m1')).toBeVisible();
  });

  test('#93 Ctrl+A selects every row', async ({ page }) => {
    await setup(page);
    await page.goto('/mail/default/inbox');
    await expect(option(page, 'Reklamácia')).toBeVisible();
    await page.locator('body').click({ position: { x: 5, y: 5 } });
    await page.keyboard.press('Control+a');
    await expect(page.getByText('Vybraté: 3')).toBeVisible();
    await shot(page, 'issue93-select-all');
  });

  test('#93 Shift+Delete asks first, then deletes for good', async ({ page }) => {
    const { bulkCalls } = await setup(page);
    await page.goto('/mail/default/inbox');
    await option(page, 'Reklamácia').click();
    await expect(page.getByText('Text m3')).toBeVisible();
    await page.keyboard.press('Shift+Delete');
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByText('Vymazať natrvalo (1)?')).toBeVisible();
    expect(bulkCalls).toEqual([]);
    await dialog.getByRole('button', { name: 'Vymazať natrvalo' }).click();
    await expect(option(page, 'Reklamácia')).toHaveCount(0);
    expect(bulkCalls).toEqual([{ action: 'purge', message_ids: ['m3'] }]);
  });

  test('#93 typing in the search field does not delete', async ({ page }) => {
    const { bulkCalls } = await setup(page);
    await page.goto('/mail/default/inbox');
    await option(page, 'Kópia faktúry 2026123').click();
    await page.getByRole('searchbox').first().click();
    await page.keyboard.type('abc');
    await page.keyboard.press('Delete');
    await expect(option(page, 'Kópia faktúry 2026123')).toHaveCount(1);
    expect(bulkCalls).toEqual([]);
  });
});
