import { DEFAULT_PREFS, expect, foldersView, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

const SIGNED_IN = { 'GET /api/auth/me': { body: ME }, 'GET /api/auth/persons': { body: ME_PICKER } };

const NOTIFS = {
  items: [
    {
      id: 'sync:mb-1',
      kind: 'sync_failed',
      title: 'Synchronizácia zlyhala',
      body: 'pilot@smartmail.test: auth_failed',
      created_at: '2026-10-27T08:00:00Z',
      unread: true,
      href: '/mail/default/inbox',
    },
    {
      id: 'assign:t-1',
      kind: 'assigned',
      title: 'Pridelené vám',
      body: 'Objednávka PO-1',
      created_at: '2026-10-26T18:00:00Z',
      unread: true,
      href: '/mail/default/inbox',
    },
  ],
  unread_count: 2,
};

async function shell(page: import('@playwright/test').Page, extra: Record<string, unknown> = {}) {
  await mockApi(page, {
    ...SIGNED_IN,
    'GET /api/mail/prefs': { body: DEFAULT_PREFS },
    'PUT /api/mail/prefs': { body: DEFAULT_PREFS },
    'GET /api/notifications': { body: NOTIFS },
    'POST /api/notifications/dismiss': { body: { ok: true } },
    'GET /api/mail/mailboxes/default/folders': { body: foldersView() },
    'GET /api/settings/mailboxes/default/provider': {
      body: { email: ME.email, imap_host: 'mail.test', imap_port: 993, provider_admin_url: 'https://provider.test/admin' },
    },
    ...extra,
  });
}

test.describe('Phase 1h-c: W13–W15b / M16 / classic', () => {
  test('W14 notifications panel Phase-1 kinds @desktop', async ({ page }, info) => {
    test.skip(info.project.name !== 'desktop', 'desktop');
    await shell(page);
    await page.goto('/mail/default/inbox');
    await page.getByRole('button', { name: /Notifikácie/ }).click();
    await expect(page.getByTestId('screen-w14')).toBeVisible();
    await expect(page.getByText('Synchronizácia zlyhala')).toBeVisible();
    await expect(page.getByText('Pridelené vám')).toBeVisible();
    await expect(page.getByText('Na schválenie')).toHaveCount(0);
    await shot(page, 'phase1hc-W14-notifs');
  });

  test('W14 empty @desktop', async ({ page }, info) => {
    test.skip(info.project.name !== 'desktop', 'desktop');
    await shell(page, { 'GET /api/notifications': { body: { items: [], unread_count: 0 } } });
    await page.goto('/mail/default/inbox');
    await page.getByRole('button', { name: /Notifikácie/ }).click();
    await expect(page.getByTestId('notifs-empty')).toBeVisible();
    await shot(page, 'phase1hc-W14-empty');
  });

  test('M16 notifications full screen @mobile', async ({ page }, info) => {
    test.skip(info.project.name !== 'mobile', 'mobile');
    await shell(page);
    await page.goto('/mail/default/inbox');
    await page.getByRole('button', { name: 'Viac' }).click();
    await page.getByRole('button', { name: 'Notifikácie' }).click();
    await expect(page.getByTestId('screen-m16')).toBeVisible();
    await expect(page.getByText('Synchronizácia zlyhala')).toBeVisible();
    await shot(page, 'phase1hc-M16-notifs');
  });

  test('W15 shortcuts dialog via ? @desktop', async ({ page }, info) => {
    test.skip(info.project.name !== 'desktop', 'desktop');
    await shell(page);
    await page.goto('/mail/default/inbox');
    await page.getByRole('navigation', { name: 'Hlavná navigácia' }).click();
    await page.keyboard.press('?');
    await expect(page.getByTestId('screen-w15')).toBeVisible();
    await expect(page.getByText('Klávesové skratky')).toBeVisible();
    await expect(page.getByText('Nová správa')).toBeVisible();
    await expect(page.getByText('Asistent')).toHaveCount(0);
    await shot(page, 'phase1hc-W15-shortcuts');
  });

  test('W15b about from rail + M18 @desktop', async ({ page }, info) => {
    test.skip(info.project.name !== 'desktop', 'desktop');
    await shell(page);
    await page.goto('/mail/default/inbox');
    await page.getByRole('button', { name: 'O systéme' }).click();
    await expect(page.getByTestId('screen-w15b')).toBeVisible();
    await expect(page.getByText('Smart Mail')).toBeVisible();
    await expect(page.getByRole('link', { name: 'Správa schránky u poskytovateľa' })).toBeVisible();
    await shot(page, 'phase1hc-W15b-about');
  });

  test('M18 opens O systéme @mobile', async ({ page }, info) => {
    test.skip(info.project.name !== 'mobile', 'mobile');
    await shell(page);
    await page.goto('/mail/default/inbox');
    await page.getByRole('button', { name: 'Viac' }).click();
    await page.getByTestId('screen-m18').getByRole('button', { name: 'O systéme' }).click();
    await expect(page.getByTestId('screen-w15b')).toBeVisible();
    await shot(page, 'phase1hc-M18-about');
  });

  test('W13 tour restart from about @desktop', async ({ page }, info) => {
    test.skip(info.project.name !== 'desktop', 'desktop');
    await shell(page);
    await page.goto('/mail/default/inbox');
    await page.evaluate(() => localStorage.setItem('sm.tour.v1', 'done'));
    await page.getByRole('button', { name: 'O systéme' }).click();
    await page.getByRole('button', { name: 'Spustiť úvodnú prehliadku' }).click();
    await expect(page.getByTestId('screen-w13')).toBeVisible();
    await expect(page.getByText('Všetko je tam, kde ste zvyknutí')).toBeVisible();
    await shot(page, 'phase1hc-W13-tour');
    await page.getByRole('button', { name: 'Ďalej' }).click();
    await expect(page.getByText('Priečinky a schránky')).toBeVisible();
  });

  test('M-W13 tour @mobile', async ({ page }, info) => {
    test.skip(info.project.name !== 'mobile', 'mobile');
    await shell(page);
    await page.goto('/mail/default/inbox');
    await page.evaluate(() => localStorage.removeItem('sm.tour.v1'));
    await page.getByRole('button', { name: 'Viac' }).click();
    await page.getByTestId('screen-m18').getByRole('button', { name: 'O systéme' }).click();
    await page.getByRole('button', { name: 'Spustiť úvodnú prehliadku' }).click();
    await expect(page.getByTestId('screen-m-w13')).toBeVisible();
    await expect(page.getByText('Pošta v mobile')).toBeVisible();
    await shot(page, 'phase1hc-MW13-tour');
  });

  test('Klasické zobrazenie banner @desktop', async ({ page }, info) => {
    test.skip(info.project.name !== 'desktop', 'desktop');
    await shell(page, {
      'GET /api/mail/prefs': {
        body: { ...DEFAULT_PREFS, ui: { ...DEFAULT_PREFS.ui, classic: true } },
      },
    });
    await page.goto('/mail/default/inbox');
    await expect(page.locator('html')).toHaveAttribute('data-classic', '1');
    await expect(page.getByTestId('classic-banner')).toBeVisible();
    await expect(page.getByText('Neprečítané')).toHaveCount(0);
    await shot(page, 'phase1hc-classic');
  });
});
