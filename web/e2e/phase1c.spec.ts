import { expect, foldersView, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

const SIGNED_IN = { 'GET /api/auth/me': { body: ME }, 'GET /api/auth/persons': { body: ME_PICKER } };

test.describe('W2 shell & folders (1c)', () => {
  test('W2 Doručená pošta: rail, folder column in Roundcube order, quota, nothing selected', async ({ page }) => {
    await mockApi(page, SIGNED_IN);
    await page.goto('/mail/default/inbox');
    const nav = page.getByRole('navigation', { name: 'Priečinky' });
    // Folder links only (first <ul>) — AI TRIEDENIE is a separate list when categories exist.
    const folderLinks = nav.locator(':scope > ul').getByRole('link');
    await expect(folderLinks).toHaveCount(13);
    await expect(folderLinks.nth(0)).toHaveAttribute('aria-current', 'page');
    await expect(page.getByRole('link', { name: 'E-mail, neprečítané: 12' })).toHaveAttribute('aria-current', 'page');
    await expect(page.getByText('Vyberte správu')).toBeVisible();
    await expect(page.getByRole('meter', { name: 'Využitie schránky' })).toHaveAttribute('aria-valuenow', '40');
    // Empty categories mock → no triage block (classic still hides it when present — see phase2b).
    await expect(page.getByTestId('ai-triage')).toHaveCount(0);
    await shot(page, 'phase1c-W2-default');
  });

  test('G3 quota above 90 % is red (plna@ fixture)', async ({ page }) => {
    const view = foldersView('plna@smartmail.test', { used_kb: 1905, limit_kb: 2048, percent: 93, level: 'danger' });
    await mockApi(page, { ...SIGNED_IN, 'GET /api/mail/mailboxes/default/folders': { body: view } });
    await page.goto('/mail/default/inbox');
    await expect(page.getByText('93 %')).toHaveClass(/text-danger-600/);
    await shot(page, 'phase1c-G3-quota-danger');
  });

  test('G3 ⋮ mailbox menu and the folder context menu', async ({ page }) => {
    const view = foldersView();
    await mockApi(page, {
      ...SIGNED_IN,
      'GET /api/mail/mailboxes': {
        body: [view.mailbox, { id: 'mb-2', email: 'senica@smartmail.test', unread: 5, sync_state: 'ok' }],
      },
    });
    await page.goto('/mail/default/inbox');
    await page.getByRole('button', { name: 'Menu schránky' }).click();
    const menu = page.getByRole('menu', { name: 'Menu schránky' });
    await expect(menu.getByRole('menuitemradio', { name: 'senica@smartmail.test' })).toBeVisible();
    await shot(page, 'phase1c-G3-mailbox-menu');
    await page.keyboard.press('Escape');
    await expect(menu).toBeHidden();
    await page.getByRole('link', { name: /^Dodávatelia/ }).click({ button: 'right' });
    await expect(page.getByRole('menu', { name: 'Akcie priečinka Dodávatelia' })).toBeVisible();
    await shot(page, 'phase1c-G3-folder-context-menu');
  });

  test('G5 Vyprázdniť Kôš: confirm dialog → G4 toast', async ({ page }) => {
    const view = foldersView();
    const trash = view.folders.find((f) => f.special_use === 'trash');
    const after = foldersView();
    const emptied = after.folders.find((f) => f.special_use === 'trash');
    if (emptied) {
      emptied.total = 0;
      emptied.unread = 0;
    }
    await mockApi(page, {
      ...SIGNED_IN,
      [`POST /api/mail/mailboxes/default/folders/${trash?.id}/empty`]: { body: after, delayMs: 200 },
    });
    await page.goto('/mail/default/inbox');
    await page.getByRole('link', { name: /^Kôš/ }).click({ button: 'right' });
    await page.getByRole('menuitem', { name: 'Vyprázdniť' }).click();
    await expect(page.getByRole('dialog', { name: 'Vyprázdniť priečinok Kôš?' })).toBeVisible();
    await shot(page, 'phase1c-G5-confirm-empty');
    await page.getByRole('dialog').getByRole('button', { name: 'Vyprázdniť' }).click();
    await expect(page.getByRole('status').filter({ hasText: 'Priečinok Kôš je vyprázdnený.' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Kôš' })).toBeVisible();
    await shot(page, 'phase1c-G4-toast');
  });

  test('G5 Nový podpriečinok form dialog', async ({ page }) => {
    await mockApi(page, SIGNED_IN);
    await page.goto('/mail/default/inbox');
    await page.getByRole('link', { name: /^Dodávatelia/ }).focus();
    await page.keyboard.press('Shift+F10');
    await page.getByRole('menuitem', { name: 'Nový podpriečinok' }).click();
    await page.getByLabel('Názov priečinka').fill('Würth');
    await shot(page, 'phase1c-G5-new-subfolder');
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).toBeHidden();
  });

  test('W2 IMAP error banner and empty folder', async ({ page }) => {
    const view = foldersView();
    view.sync = { state: 'error', error: 'unavailable', last_synced_at: null };
    await mockApi(page, {
      ...SIGNED_IN,
      'GET /api/mail/mailboxes/default/folders': { body: view },
      'POST /api/mail/mailboxes/default/refresh': {
        status: 503,
        body: { detail: { code: 'mail_server_unavailable' } },
      },
    });
    const smart = view.folders.find((f) => f.name === 'Smart');
    await page.goto(`/mail/default/${smart?.id}`);
    await expect(page.getByText('Nepodarilo sa načítať priečinok – skúšame znova.')).toBeVisible();
    await expect(page.getByText('Priečinok je prázdny')).toBeVisible();
    await shot(page, 'phase1c-W2-imap-error-empty');
    await page.getByRole('button', { name: 'Skúsiť znova' }).click();
    await expect(page.getByText('Nepodarilo sa načítať priečinok – skúšame znova.')).toBeVisible();
  });

  test('G6 offline banner', async ({ page, context }) => {
    await mockApi(page, SIGNED_IN);
    await page.goto('/mail/default/inbox');
    await expect(page.getByRole('navigation', { name: 'Priečinky' })).toBeVisible();
    await context.setOffline(true);
    await expect(page.getByText('Ste offline – zobrazujeme uložené správy, odoslanie počká.')).toBeVisible();
    await shot(page, 'phase1c-G6-offline');
    await context.setOffline(false);
    await expect(page.getByText('Ste offline – zobrazujeme uložené správy, odoslanie počká.')).toBeHidden();
  });

  test('G7 drop zone while a file is dragged over the window', async ({ page }) => {
    await mockApi(page, SIGNED_IN);
    await page.goto('/mail/default/inbox');
    await expect(page.getByRole('navigation', { name: 'Priečinky' })).toBeVisible();
    await page.evaluate(() => {
      const data = new DataTransfer();
      data.items.add(new File(['x'], 'faktura.pdf', { type: 'application/pdf' }));
      window.dispatchEvent(new DragEvent('dragenter', { dataTransfer: data }));
    });
    await expect(page.getByText('Pustite súbor sem – doklad dodávateľa alebo objednávka')).toBeVisible();
    await shot(page, 'phase1c-G7-dropzone');
  });

  test('W2b one-person chip menu: Môj profil and Odhlásiť', async ({ page }) => {
    await mockApi(page, { ...SIGNED_IN, 'POST /api/auth/logout': { body: { ok: true } } });
    await page.goto('/mail/default/inbox');
    await page.getByRole('button', { name: 'Pracuje: Jana Testová' }).click();
    const menu = page.getByRole('menu', { name: 'Menu osoby' });
    await expect(menu.getByRole('menuitem', { name: 'Môj profil' })).toBeFocused();
    await expect(menu.getByRole('menuitem', { name: 'Odhlásiť' })).toBeVisible();
    await shot(page, 'phase1c-W2b-chip-menu-one-person');
    await menu.getByRole('menuitem', { name: 'Môj profil' }).click();
    await expect(page).toHaveURL(/\/settings\/identity\/profile$/);
    await expect(page.getByRole('heading', { name: 'Nastavenia › Môj profil' })).toBeVisible();
    await shot(page, 'phase1c-W12-profile-placeholder');
    await page.getByRole('button', { name: 'Odhlásiť' }).click();
    await expect(page).toHaveURL(/\/login$/);
  });

  test('G1 below 820 px height Tmavý režim and O systéme move into the PersonChip menu', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 760 });
    await mockApi(page, SIGNED_IN);
    await page.goto('/mail/default/inbox');
    await expect(page.getByRole('button', { name: 'Tmavý režim' })).toHaveCount(0);
    await page.getByRole('button', { name: 'Pracuje: Jana Testová' }).click();
    await expect(page.getByRole('menuitem', { name: 'Tmavý režim' })).toBeVisible();
    await expect(page.getByRole('menuitem', { name: 'O systéme' })).toBeVisible();
    await shot(page, 'phase1c-G1-low-rail-chip-menu');
  });

  test('W2 on a phone: mobile shell + folder drawer (1h-a M1/M2) @mobile', async ({ page }, info) => {
    test.skip(info.project.name !== 'mobile', 'mobile frame only');
    await mockApi(page, SIGNED_IN);
    await page.goto('/mail/default/inbox');
    await expect(page.getByTestId('mobile-shell')).toBeVisible();
    await expect(page.getByTestId('bottom-nav')).toBeVisible();
    await page.getByTestId('mobile-app-bar').getByRole('button', { name: 'Priečinky' }).first().click();
    await expect(page.getByTestId('folder-drawer')).toBeVisible();
    await expect(page.getByRole('dialog', { name: 'Priečinky' })).toBeVisible();
    await shot(page, 'phase1c-W2-mobile-shell');
  });
});
