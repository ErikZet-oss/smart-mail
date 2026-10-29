import { expect, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

/** Issue #77 PR 1: W12-09 „Dvojstupňové overenie“ (Figma `67:58683`, `67:58896`). Fictional secret and codes. */
const NAV = { sections: [{ id: '09', path: 'security', title: 'Bezpečnosť', subs: [] }] };
const SECRET = 'JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP';
const CODES = [
  '4f7k-2m9q',
  '8plx-3v6t',
  'q2w9-hj4r',
  '7nmb-5c8z',
  'd3k8-9pwe',
  'x5t2-6yql',
  'r8v4-1ghs',
  'm6j9-2kdn',
  'z1p5-8qrt',
  'h4c7-3lwx',
];

test('#77 W12-09 enable 2FA: QR, key, backup codes and the code from the app @mobile', async ({ page }, info) => {
  let enabled = false;
  const confirms: unknown[] = [];
  await mockApi(page, {
    'GET /api/auth/me': { body: ME },
    'GET /api/auth/persons': { body: ME_PICKER },
    'GET /api/settings/nav': { body: NAV },
    'GET /api/settings/security/sessions': { body: [] },
    'GET /api/settings/security/2fa': () => ({
      body: { available: true, enabled, required: false, backup_codes_left: enabled ? 10 : 0 },
    }),
    'POST /api/settings/security/2fa/start': {
      body: {
        secret: SECRET,
        otpauth_uri: `otpauth://totp/Smart%20Mail%3Ajana%40smartmail.test?secret=${SECRET}&issuer=Smart%20Mail`,
        backup_codes: CODES,
      },
    },
    'POST /api/settings/security/2fa/confirm': (body) => {
      confirms.push(body);
      if ((body as { code: string }).code !== '123456') {
        return { status: 422, body: { detail: { code: 'totp_invalid' } } };
      }
      enabled = true;
      return { body: { enabled: true } };
    },
  });
  await page.goto('/settings/security');
  const row = page.getByTestId('two-factor');
  await expect(row).toContainText('vypnuté');
  await row.getByRole('button', { name: 'Zapnúť' }).click();

  const dialog = page.getByRole('dialog', { name: 'Zapnúť dvojstupňové overenie' });
  await expect(dialog.getByRole('img', { name: 'QR kód pre aplikáciu na overovanie' })).toBeVisible();
  await expect(dialog.getByTestId('two-factor-secret')).toHaveText('JBSW Y3DP EHPK 3PXP JBSW Y3DP EHPK 3PXP');
  await expect(dialog.getByTestId('backup-codes').getByRole('listitem')).toHaveCount(10);
  await expect(dialog.getByRole('button', { name: 'Zapnúť' })).toBeDisabled();
  await shot(page, `issue77-W12-09-enable-${info.project.name}`);

  await dialog.getByPlaceholder('6 číslic').fill('000000');
  await dialog.getByRole('button', { name: 'Zapnúť' }).click();
  await expect(dialog).toContainText('Nesprávny kód.');
  await dialog.getByPlaceholder('6 číslic').fill('123456');
  await dialog.getByRole('button', { name: 'Zapnúť' }).click();
  await expect(dialog).toHaveCount(0);
  await expect(row).toContainText('zapnuté');
  expect(confirms).toEqual([{ code: '000000' }, { code: '123456' }]);
});

test('#77 W12-09 disable 2FA asks for the password first', async ({ page }) => {
  let reauthed = false;
  let disabled = false;
  await mockApi(page, {
    'GET /api/auth/me': { body: ME },
    'GET /api/auth/persons': { body: ME_PICKER },
    'GET /api/settings/nav': { body: NAV },
    'GET /api/settings/security/sessions': { body: [] },
    'GET /api/settings/security/2fa': () => ({
      body: { available: true, enabled: !disabled, required: false, backup_codes_left: 10 },
    }),
    'POST /api/settings/security/2fa/disable': () => {
      if (!reauthed) return { status: 401, body: { detail: { code: 'reauth_required' } } };
      disabled = true;
      return { body: { enabled: false } };
    },
    'POST /api/auth/reauth': () => {
      reauthed = true;
      return { body: { valid_s: 900 } };
    },
  });
  await page.goto('/settings/security');
  await page.getByTestId('two-factor').getByRole('button', { name: 'Vypnúť' }).click();
  await page
    .getByRole('dialog', { name: 'Vypnúť dvojstupňové overenie?' })
    .getByRole('button', { name: 'Vypnúť' })
    .click();
  const reauth = page.getByRole('dialog', { name: 'Potvrďte heslom' });
  await reauth.getByLabel('Heslo k e-mailu').fill('Spravne-Heslo-1');
  await reauth.getByRole('button', { name: 'Potvrdiť' }).click();
  await expect(page.getByTestId('two-factor')).toContainText('vypnuté');
  expect(disabled).toBe(true);
});
