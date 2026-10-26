import { expect, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

const EMAIL = 'eshop@smartsro.sk';
const PASSWORD = 'heslo12345';

async function fillLogin(page: import('@playwright/test').Page) {
  await page.getByLabel('E-mail').fill(EMAIL);
  await page.getByLabel('Heslo', { exact: true }).fill(PASSWORD);
}

test.describe('W1 Prihlásenie', () => {
  test('default @mobile', async ({ page }, info) => {
    await mockApi(page, {});
    await page.goto('/login');
    await expect(page.getByRole('button', { name: 'PRIHLÁSIŤ' })).toBeVisible();
    await expect(page.getByLabel('E-mail')).toBeFocused();
    await shot(page, `W1-default-${info.project.name}`);
  });

  test('M-W1 follows its frame: checkbox above the button, no eye toggle, no footer @mobile', async ({
    page,
  }, info) => {
    test.skip(info.project.name !== 'mobile', 'mobile frame only');
    await mockApi(page, { 'POST /api/auth/login': { status: 401, body: { detail: { code: 'invalid_credentials' } } } });
    await page.goto('/login');
    const remember = await page.getByText('Zostať prihlásený na tomto zariadení').boundingBox();
    const button = await page.getByRole('button', { name: 'PRIHLÁSIŤ' }).boundingBox();
    expect(remember && button && remember.y < button.y).toBe(true);
    await expect(page.getByRole('button', { name: 'Zobraziť heslo' })).toBeHidden();
    await expect(page.getByText(/^Smart Mail/)).toBeHidden();
    await fillLogin(page);
    await page.getByRole('button', { name: 'PRIHLÁSIŤ' }).click();
    await expect(page.getByRole('alert')).toHaveText('Nesprávny e-mail alebo heslo.');
    await page.mouse.click(5, 5);
    await shot(page, 'W1-invalid-mobile');
  });

  for (const [name, status, detail, text] of [
    ['invalid', 401, { code: 'invalid_credentials' }, 'Nesprávny e-mail alebo heslo.'],
    ['server-down', 503, { code: 'mail_server_unavailable' }, 'Mailový server je nedostupný – skúste o chvíľu.'],
    ['rate-limited', 429, { code: 'rate_limited', retry_after: 300 }, 'Príliš veľa pokusov, skúste o 5 minút.'],
  ] as const) {
    test(`error: ${name}`, async ({ page }) => {
      await mockApi(page, { 'POST /api/auth/login': { status, body: { detail } } });
      await page.goto('/login');
      await fillLogin(page);
      await page.getByRole('button', { name: 'PRIHLÁSIŤ' }).click();
      await expect(page.getByRole('alert')).toHaveText(text);
      await page.getByRole('button', { name: 'PRIHLÁSIŤ' }).focus();
      await page.mouse.click(5, 5);
      await shot(page, `W1-${name}`);
    });
  }

  test('submitting + Caps Lock', async ({ page }) => {
    await mockApi(page, { 'POST /api/auth/login': { body: null, never: true } });
    await page.goto('/login');
    await fillLogin(page);
    await page.getByLabel('Heslo', { exact: true }).dispatchEvent('keyup', { key: 'A', modifierCapsLock: true });
    await expect(page.getByText('Zapnutý Caps Lock')).toBeVisible();
    await page.getByRole('button', { name: 'PRIHLÁSIŤ' }).click();
    await expect(page.getByRole('button', { name: 'PRIHLASUJEM…' })).toBeDisabled();
    await shot(page, 'W1-submitting-capslock');
  });

  test('signs in and lands on Doručená pošta (W2)', async ({ page }) => {
    await mockApi(page, {
      'POST /api/auth/login': { body: { next: 'app', me: ME } },
      'GET /api/auth/me': { body: ME },
      'GET /api/auth/persons': { body: ME_PICKER },
    });
    await page.goto('/login');
    await fillLogin(page);
    await page.getByRole('button', { name: 'PRIHLÁSIŤ' }).click();
    await expect(page).toHaveURL(/\/mail\/default\/inbox$/);
    await expect(page.getByRole('link', { name: /^Doručená pošta/ })).toHaveAttribute('aria-current', 'page');
  });
});

test.describe('W1c', () => {
  for (const reason of ['password-changed', 'expired']) {
    test(reason, async ({ page }) => {
      await mockApi(page, {});
      await page.goto(`/login?reason=${reason}`);
      await expect(page.getByLabel('E-mail')).toBeFocused();
      await shot(page, `W1c-${reason}`);
    });
  }

  test('a revoked session on a deep link ends on W1c and returns there after login', async ({ page }) => {
    let signedIn = false;
    await mockApi(page, { 'GET /api/auth/persons': { body: ME_PICKER } });
    await page.route('**/api/auth/me', (route) =>
      signedIn
        ? route.fulfill({ json: ME })
        : route.fulfill({ status: 401, json: { detail: { code: 'unauthenticated', reason: 'password_changed' } } }),
    );
    await page.route('**/api/auth/login', (route) => {
      signedIn = true;
      return route.fulfill({ json: { next: 'app', me: ME } });
    });
    await page.goto('/mail/nitra/INBOX');
    await expect(page).toHaveURL(/reason=password-changed/);
    await fillLogin(page);
    await page.getByRole('button', { name: 'PRIHLÁSIŤ' }).click();
    await expect(page).toHaveURL(/\/mail\/nitra\/INBOX$/);
  });
});

test.describe('W1a Overenie (2FA)', () => {
  test('default', async ({ page }) => {
    await mockApi(page, {});
    await page.goto('/login/2fa');
    await expect(page.getByLabel('Číslica 1 zo 6')).toBeFocused();
    await shot(page, 'W1a-default');
  });

  test('wrong code', async ({ page }) => {
    await mockApi(page, {
      'POST /api/auth/2fa': { status: 401, body: { detail: { code: 'invalid_code', attempts_left: 3 } } },
    });
    await page.goto('/login/2fa');
    await expect(page.getByLabel('Číslica 1 zo 6')).toBeFocused();
    await page.keyboard.type('481920');
    await page.getByRole('button', { name: 'Overiť' }).click();
    await expect(page.getByRole('alert')).toHaveText('Kód nie je správny. Zostávajú 3 pokusy.');
    await expect(page.getByLabel('Číslica 1 zo 6')).toBeFocused();
    await page.keyboard.type('481');
    await shot(page, 'W1a-error');
  });
});

test.describe('W16 / W17', () => {
  test('W16a 403', async ({ page }) => {
    await mockApi(page, { 'GET /api/system/info': { body: { admin_contact_email: 'it@smartsro.sk' } } });
    await page.goto('/403');
    await expect(page.getByRole('heading', { name: 'Nemáte prístup k tejto stránke' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Požiadať správcu' })).toHaveAttribute(
      'href',
      /^mailto:it%40smartsro\.sk\?subject=/,
    );
    await shot(page, 'W16a');
  });

  test('W16b 404 for an unknown route', async ({ page }) => {
    await mockApi(page, {});
    await page.goto('/neexistuje/nic');
    await expect(page.getByRole('heading', { name: 'Stránku sme nenašli' })).toBeVisible();
    await shot(page, 'W16b');
  });

  test('W16c 500 with reference', async ({ page }) => {
    await mockApi(page, {});
    await page.goto('/500?ref=7F3A21C9');
    await expect(page.getByText('500 · ref. 7F3A-21C9')).toBeVisible();
    await shot(page, 'W16c');
  });

  test('W17 maintenance, back to the app when it ends', async ({ page }) => {
    let active = true;
    await page.clock.setFixedTime(new Date('2026-10-27T06:40:00+01:00'));
    await mockApi(page, {});
    await page.route('**/api/system/maintenance', (route) =>
      route.fulfill({ json: { active, until: '2026-10-27T08:00:00+01:00' } }),
    );
    await page.goto('/maintenance');
    await expect(page.getByText(/Smart Mail bude opäť dostupný dnes približne o 8:00\./)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Skúsiť znova' })).toBeEnabled();
    await shot(page, 'W17');
    active = false;
    await page.getByRole('button', { name: 'Skúsiť znova' }).click();
    await expect(page).not.toHaveURL(/maintenance/);
  });
});
