import { expect, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

/** Issue #77 PR 2: „Vyžadovať 2FA“ — a login without TOTP goes to the setup and only then into the app; the admin
 * sets the flag and can reset 2FA in W12-10. Fictional data. */
const SECRET = 'JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP';
const CODES = Array.from({ length: 10 }, (_, i) => `ab${i}d-ef${i}h`);

test('#77 W1 → setup: a login that must set up 2FA reaches the app only after it @mobile', async ({ page }, info) => {
  let enabled = false;
  await mockApi(page, {
    'GET /api/auth/me': () =>
      enabled
        ? { body: { ...ME, mfa_setup_required: false } }
        : { status: 401, body: { detail: { code: 'unauthenticated', reason: 'missing' } } },
    'GET /api/auth/persons': { body: ME_PICKER },
    'POST /api/auth/login': { body: { next: '2fa-setup', me: null } },
    'POST /api/settings/security/2fa/start': {
      body: { secret: SECRET, otpauth_uri: `otpauth://totp/Smart%20Mail?secret=${SECRET}`, backup_codes: CODES },
    },
    'POST /api/settings/security/2fa/confirm': () => {
      enabled = true;
      return { body: { enabled: true } };
    },
  });
  await page.goto('/login');
  await page.getByLabel('E-mail').fill('jana@smartmail.test');
  await page.getByLabel('Heslo', { exact: true }).fill('heslo-fiktivne');
  await page.getByRole('button', { name: 'PRIHLÁSIŤ' }).click();

  const setup = page.getByTestId('mfa-setup');
  await expect(setup.getByRole('heading', { name: 'Nastavte dvojstupňové overenie' })).toBeVisible();
  await expect(page).toHaveURL(/\/login\/2fa\?setup=1/);
  await shot(page, `issue77-W1a-setup-${info.project.name}`);
  await setup.getByRole('button', { name: 'Nastaviť' }).click();
  const dialog = page.getByRole('dialog', { name: 'Zapnúť dvojstupňové overenie' });
  await dialog.getByPlaceholder('6 číslic').fill('123456');
  await dialog.getByRole('button', { name: 'Zapnúť' }).click();
  await expect(page).not.toHaveURL(/\/login/);
});

test('#77 W12-10 admin requires 2FA and resets it @mobile', async ({ page }, info) => {
  const ADMIN = { ...ME, person: { ...ME.person, role: 'admin' } };
  const eva = {
    id: 'a-eva',
    email: 'eva@smartsro.sk',
    kind: 'personal',
    active: true,
    last_login_at: null,
    branch_id: null,
    branch_name: null,
    persons_count: null,
    require_2fa: false,
    totp_enabled: true,
    person: { id: 'p-eva', first_name: 'Eva', last_name: 'Testová', role: 'sales', active: true },
  };
  const patches: unknown[] = [];
  let resets = 0;
  await mockApi(page, {
    'GET /api/auth/me': { body: ADMIN },
    'GET /api/auth/persons': { body: { ...ME_PICKER, persons: [ADMIN.person] } },
    'GET /api/settings/nav': {
      body: { sections: [{ id: '10', path: 'users', title: 'Používatelia a role', subs: [] }] },
    },
    'GET /api/settings/admin/users': { body: [eva] },
    'GET /api/settings/admin/branches': { body: [] },
    'PATCH /api/settings/admin/users/a-eva': (body) => {
      patches.push(body);
      return { body: { ...eva, require_2fa: true } };
    },
    'POST /api/settings/admin/users/a-eva/reset-2fa': () => {
      resets += 1;
      return { body: { ...eva, totp_enabled: false } };
    },
  });
  await page.goto('/settings/users');
  const row = page.getByTestId('user-2fa');
  await expect(row).toContainText('zapnuté');
  await row.getByRole('switch', { name: 'Vyžadovať 2FA' }).click();
  await shot(page, `issue77-W12-10-require-${info.project.name}`);
  await page.getByTestId('user-detail').getByRole('button', { name: 'Uložiť' }).click();
  await expect.poll(() => patches.at(-1)).toMatchObject({ require_2fa: true });

  await row.getByRole('button', { name: 'Resetovať 2FA' }).click();
  await page
    .getByRole('dialog', { name: 'Resetovať dvojstupňové overenie pre eva@smartsro.sk?' })
    .getByRole('button', { name: 'Resetovať 2FA' })
    .click();
  await expect(page.getByText('Dvojstupňové overenie bolo resetované.')).toBeVisible();
  expect(resets).toBe(1);
});
