import type { Page } from '@playwright/test';

import { DEFAULT_PREFS, expect, foldersView, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

// #96 Presunúť do… / Kopírovať do… (Viac menu, bulk bar, L, mobile).

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
  const bulkCalls: { action: string; message_ids: string[]; dest_folder_id?: string }[] = [];
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
      const body = payload as { action: string; message_ids: string[]; dest_folder_id?: string };
      bulkCalls.push(body);
      if (['delete', 'purge', 'move'].includes(body.action)) body.message_ids.forEach((id) => gone.add(id));
      return { body: { ok: body.message_ids.length } };
    },
    'PUT /api/mail/prefs': { body: DEFAULT_PREFS },
  });
  return { bulkCalls };
}

const option = (page: Page, subject: string) => page.getByRole('option').filter({ hasText: subject });
const FAKTURY = foldersView().folders.find((f) => f.name === 'Faktúry')?.id ?? '';

async function openFirst(page: Page) {
  await page.goto('/mail/default/inbox');
  await option(page, 'Kópia faktúry 2026123').click();
  await expect(page.getByText('Text m1')).toBeVisible();
}

async function viac(page: Page) {
  await page.getByRole('button', { name: 'Viac', exact: true }).last().click();
}

test.describe('#96 move / copy @mobile', () => {
  test('#96 Viac › Presunúť do… › Faktúry moves the message', async ({ page }, info) => {
    const { bulkCalls } = await setup(page);
    await openFirst(page);
    await viac(page);
    await page.getByRole('menuitem', { name: 'Presunúť do…' }).click();
    const picker = page.getByRole('menu', { name: 'Presunúť do…' });
    await expect(picker.getByRole('menuitem').first()).toHaveText(/Doručená pošta/);
    await shot(page, `issue96-picker-${info.project.name}`);
    await picker.getByRole('menuitem', { name: 'Faktúry' }).click();
    await expect(page.getByText('Presunuté do priečinka Faktúry.')).toBeVisible();
    await expect(option(page, 'Kópia faktúry 2026123')).toHaveCount(0);
    await expect.poll(() => bulkCalls).toEqual([{ action: 'move', message_ids: ['m1'], dest_folder_id: FAKTURY }]);
  });

  test('#96 Kopírovať do… keeps the row', async ({ page }) => {
    const { bulkCalls } = await setup(page);
    await openFirst(page);
    await viac(page);
    await page.getByRole('menuitem', { name: 'Kopírovať do…' }).click();
    await page.getByRole('menu', { name: 'Kopírovať do…' }).getByRole('menuitem', { name: 'Faktúry' }).click();
    await expect(page.getByText('Skopírované do priečinka Faktúry.')).toBeVisible();
    await expect.poll(() => bulkCalls).toEqual([{ action: 'copy', message_ids: ['m1'], dest_folder_id: FAKTURY }]);
    await page.goto('/mail/default/inbox');
    await expect(option(page, 'Kópia faktúry 2026123')).toHaveCount(1);
  });

  test('#96 the current folder cannot be picked', async ({ page }) => {
    await setup(page);
    await openFirst(page);
    await viac(page);
    await page.getByRole('menuitem', { name: 'Presunúť do…' }).click();
    await expect(
      page.getByRole('menu', { name: 'Presunúť do…' }).getByRole('menuitem', { name: 'Doručená pošta' }),
    ).toHaveAttribute('aria-disabled', 'true');
  });
});

test.describe('#96 move from the list', () => {
  test('#96 L opens the picker for the open message', async ({ page }) => {
    const { bulkCalls } = await setup(page);
    await openFirst(page);
    await page.keyboard.press('l');
    await page.getByRole('menu', { name: 'Presunúť do…' }).getByRole('menuitem', { name: 'Faktúry' }).click();
    await expect(option(page, 'Kópia faktúry 2026123')).toHaveCount(0);
    await expect.poll(() => bulkCalls).toEqual([{ action: 'move', message_ids: ['m1'], dest_folder_id: FAKTURY }]);
  });

  test('#96 bulk bar Presunúť moves every selected row', async ({ page }) => {
    const { bulkCalls } = await setup(page);
    await page.goto('/mail/default/inbox');
    await expect(option(page, 'Reklamácia')).toBeVisible();
    await page.locator('body').click({ position: { x: 5, y: 5 } });
    await page.keyboard.press('Control+a');
    // #185: Presunúť lives in the ⋯ menu of the bulk bar (Figma M1 multi-select)
    await page.getByTestId('bulk-toolbar').getByRole('button', { name: 'Viac' }).click();
    await page.getByRole('menuitem', { name: 'Presunúť' }).click();
    await page.getByRole('menu', { name: 'Presunúť do…' }).getByRole('menuitem', { name: 'Faktúry' }).click();
    await expect(page.getByRole('option')).toHaveCount(0);
    await expect
      .poll(() => bulkCalls)
      .toEqual([{ action: 'move', message_ids: ['m1', 'm2', 'm3'], dest_folder_id: FAKTURY }]);
  });
});

test.describe('#96 drag & drop', () => {
  test('#96 dragging a row onto Faktúry moves it', async ({ page }) => {
    const { bulkCalls } = await setup(page);
    await page.goto('/mail/default/inbox');
    const faktury = page.locator(`[data-folder-id="${FAKTURY}"]`);
    await option(page, 'Cenová ponuka M10×30 A2').dragTo(faktury);
    await expect(page.getByText('Presunuté do priečinka Faktúry.')).toBeVisible();
    await expect(option(page, 'Cenová ponuka M10×30 A2')).toHaveCount(0);
    await expect.poll(() => bulkCalls).toEqual([{ action: 'move', message_ids: ['m2'], dest_folder_id: FAKTURY }]);
  });

  test('#96 dragging the selection moves every selected row; the own folder is no target', async ({ page }) => {
    const { bulkCalls } = await setup(page);
    await page.goto('/mail/default/inbox');
    await expect(option(page, 'Reklamácia')).toBeVisible();
    const inbox = page.locator(`[data-folder-id="${foldersView().folders[0]?.id ?? ''}"]`);
    await option(page, 'Reklamácia').dragTo(inbox);
    expect(bulkCalls).toEqual([]);
    await page.locator('body').click({ position: { x: 5, y: 5 } });
    await page.keyboard.press('Control+a');
    await option(page, 'Reklamácia').dragTo(page.locator(`[data-folder-id="${FAKTURY}"]`));
    await expect(page.getByRole('option')).toHaveCount(0);
    await expect
      .poll(() => bulkCalls)
      .toEqual([{ action: 'move', message_ids: ['m1', 'm2', 'm3'], dest_folder_id: FAKTURY }]);
  });
});
