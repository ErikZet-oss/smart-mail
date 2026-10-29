import { expect, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

/** Issue #54: a ⚠ admin change answered 401 `reauth_required` opens „Potvrďte heslom“, a wrong password keeps the
 * dialog (no logout), the right one repeats the change. Fictional data. */
const ADMIN = { ...ME, person: { ...ME.person, role: 'admin' } };
const NAV = { sections: [{ id: '10', path: 'users', title: 'Používatelia a role', subs: [] }] };
const EVA = {
  id: 'a-eva',
  email: 'eva@smartsro.sk',
  kind: 'personal',
  active: true,
  last_login_at: null,
  branch_id: null,
  branch_name: null,
  persons_count: null,
  person: { id: 'p-eva', first_name: 'Eva', last_name: 'Testová', role: 'sales', active: true },
};

test('#54 W12-10 re-auth dialog: wrong password stays signed in, right one saves @mobile', async ({ page }, info) => {
  let reauthed = false;
  const patches: unknown[] = [];
  const passwords: string[] = [];
  await mockApi(page, {
    'GET /api/auth/me': { body: ADMIN },
    'GET /api/auth/persons': { body: { ...ME_PICKER, persons: [ADMIN.person] } },
    'GET /api/settings/nav': { body: NAV },
    'GET /api/settings/admin/users': { body: [EVA] },
    'GET /api/settings/admin/branches': { body: [] },
    'PATCH /api/settings/admin/users/a-eva': (body) => {
      if (!reauthed) return { status: 401, body: { detail: { code: 'reauth_required' } } };
      patches.push(body);
      return { body: { ...EVA, person: { ...EVA.person, role: 'accounting' } } };
    },
    'POST /api/auth/reauth': (body) => {
      const password = String((body as { password: string }).password);
      passwords.push(password);
      if (password !== 'Spravne-Heslo-1') return { status: 422, body: { detail: { code: 'reauth_failed' } } };
      reauthed = true;
      return { body: { valid_s: 900 } };
    },
  });
  await page.goto('/settings/users');
  const detail = page.getByTestId('user-detail');
  await detail.getByLabel('Rola').selectOption('accounting');
  await detail.getByRole('button', { name: 'Uložiť' }).click();

  const dialog = page.getByRole('dialog', { name: 'Potvrďte heslom' });
  await dialog.getByLabel('Heslo k e-mailu').fill('zle');
  await dialog.getByRole('button', { name: 'Potvrdiť' }).click();
  await expect(dialog).toContainText('Nesprávne heslo. Skúste to znova.');
  await expect(page).toHaveURL(/\/settings\/users/); // not signed out
  await shot(page, `issue54-reauth-${info.project.name}`);

  await dialog.getByLabel('Heslo k e-mailu').fill('Spravne-Heslo-1');
  await dialog.getByRole('button', { name: 'Potvrdiť' }).click();
  await expect(dialog).toHaveCount(0);
  await expect.poll(() => patches.at(-1)).toMatchObject({ role: 'accounting' });
  await expect(page.getByText('Nastavenia uložené.')).toBeVisible();
  expect(passwords).toEqual(['zle', 'Spravne-Heslo-1']);
});

test('#54 cancelling the re-auth keeps the page and does not save', async ({ page }) => {
  let patches = 0;
  await mockApi(page, {
    'GET /api/auth/me': { body: ADMIN },
    'GET /api/auth/persons': { body: { ...ME_PICKER, persons: [ADMIN.person] } },
    'GET /api/settings/nav': { body: NAV },
    'GET /api/settings/admin/users': { body: [EVA] },
    'GET /api/settings/admin/branches': { body: [] },
    'PATCH /api/settings/admin/users/a-eva': () => {
      patches += 1;
      return { status: 401, body: { detail: { code: 'reauth_required' } } };
    },
  });
  await page.goto('/settings/users');
  const detail = page.getByTestId('user-detail');
  await detail.getByLabel('Rola').selectOption('accounting');
  await detail.getByRole('button', { name: 'Uložiť' }).click();
  const dialog = page.getByRole('dialog', { name: 'Potvrďte heslom' });
  await dialog.getByRole('button', { name: 'Zrušiť' }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page).toHaveURL(/\/settings\/users/);
  expect(patches).toBe(1);
});
