import { expect, test } from './fixtures';

/** Pilot #18 B2: hung /api/auth/me must show an error screen, not a blank dark page. */
test('B2 F5 with hung /api/auth/me shows Skúsiť znova (not blank)', async ({ page }) => {
  await page.route('**/api/auth/csrf', (route) => route.fulfill({ status: 204, body: '' }));
  await page.route('**/api/auth/me', async (route) => {
    await new Promise((r) => setTimeout(r, 15_000));
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        account_id: 'a1',
        email: 'late@smartmail.test',
        kind: 'personal',
        branch: null,
        person: null,
        needs_person: false,
        read_only: false,
      }),
    });
  });
  await page.route('**/api/**', (route) => {
    if (route.request().url().includes('/api/auth/')) return route.fallback();
    return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
  });

  await page.goto('/mail/default/inbox');
  await expect(page.getByTestId('shell-loading')).toBeVisible({ timeout: 3_000 });
  await expect(page.getByTestId('shell-load-error')).toBeVisible({ timeout: 12_000 });
  await expect(page.getByRole('button', { name: 'Skúsiť znova' })).toBeVisible();
  // Must not stay as an empty dark main with only aria-busy
  await expect(page.locator('main[aria-busy="true"]:not([data-testid])')).toHaveCount(0);
});
