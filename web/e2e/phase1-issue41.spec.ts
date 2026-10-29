import type { Page } from '@playwright/test';

import { DEFAULT_PREFS, expect, foldersView, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

/** Issue #41: sync errors are visible, large first syncs show progress, a 500 on a message is an error state. */
const SIGNED_IN = { 'GET /api/auth/me': { body: ME }, 'GET /api/auth/persons': { body: ME_PICKER } };

function list(folderId: string) {
  return {
    mode: 'list' as const,
    total: 1,
    page: 1,
    page_size: 50,
    messages: [
      {
        id: 'm-1',
        thread_id: null,
        folder_id: folderId,
        uid: 1,
        subject: 'Objednávka 4471',
        from_name: 'Ján Novák',
        from_email: 'novak@abcstav.example',
        preview: 'Dobrý deň, objednávame…',
        received_at: '2026-10-26T07:42:00Z',
        sent_at: '2026-10-26T07:42:00Z',
        size: 1200,
        seen: false,
        flagged: false,
        answered: false,
        has_attachments: false,
        thread_count: 1,
      },
    ],
    threads: [] as unknown[],
    prefs: DEFAULT_PREFS.list,
  };
}

async function mockMail(page: Page, sync: Record<string, unknown>, extras: Record<string, unknown> = {}) {
  const view = { ...foldersView(), sync: { ...foldersView().sync, ...sync } };
  const inbox = view.folders.find((f) => f.special_use === 'inbox') ?? view.folders[0];
  if (!inbox) throw new Error('foldersView has no inbox');
  await mockApi(page, {
    ...SIGNED_IN,
    'GET /api/mail/mailboxes/default/folders': { body: view },
    [`GET /api/mail/mailboxes/default/folders/${inbox.id}/messages`]: { body: list(inbox.id) },
    ...(extras as Record<string, { body: unknown; status?: number }>),
  });
}

test('#41 large first sync shows "Načítava sa schránka… 12 400 / 25 000" @mobile', async ({ page }, info) => {
  await mockMail(page, { loaded: 12400, total: 25000 });
  await page.goto('/mail/default/inbox');
  await expect(page.getByTestId('sync-progress')).toHaveText(/Načítava sa schránka… 12\s400 \/ 25\s000/);
  await shot(page, `issue41-sync-progress-${info.project.name}`);
});

test('#41 sync error shows the G6 banner "Synchronizácia schránky zlyhala" @mobile', async ({ page }, info) => {
  await mockMail(page, { state: 'error', error: 'ValueError' });
  await page.goto('/mail/default/inbox');
  await expect(page.getByText('Synchronizácia schránky zlyhala – skúšame znova')).toBeVisible();
  await expect(page.getByTestId('sync-progress')).toHaveCount(0);
  await shot(page, `issue41-sync-error-${info.project.name}`);
});

test('#41 a 500 on the message shows the error state with the ref code @mobile', async ({ page }, info) => {
  await mockMail(
    page,
    {},
    {
      'GET /api/mail/mailboxes/default/messages/m-1': {
        status: 500,
        body: { detail: { code: 'server_error', ref: '7f3a21c9' } },
      },
    },
  );
  await page.goto('/mail/default/inbox');
  await page.getByText('Objednávka 4471').first().click();
  const error = page.getByTestId('message-load-error');
  await expect(error).toContainText('Nepodarilo sa načítať správu.');
  await expect(error).toContainText('7F3A-21C9');
  await expect(error.getByRole('button', { name: 'Skúsiť znova' })).toBeVisible();
  await expect(page).not.toHaveURL(/\/500/);
  await shot(page, `issue41-message-error-${info.project.name}`);
});
