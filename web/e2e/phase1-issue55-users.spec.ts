import type { Page } from '@playwright/test';

import { expect, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

/** Issue #55 part 2: Settings 10 Používatelia a role as in Figma W12-10 `68:59425` / chyba `68:59659`. Fictional. */
const ADMIN = { ...ME, person: { ...ME.person, role: 'admin' } };
const NAV = { sections: [{ id: '10', path: 'users', title: 'Používatelia a role', subs: [] }] };
const TODAY = new Date().toISOString();
const USERS = [
  {
    id: 'a-erik',
    email: 'erik@smartsro.sk',
    kind: 'personal',
    active: true,
    last_login_at: TODAY,
    branch_id: null,
    branch_name: null,
    persons_count: null,
    person: { id: 'p-erik', first_name: 'Erik', last_name: 'Testový', role: 'admin', active: true },
  },
  {
    id: 'a-senica',
    email: 'senica@smartsro.sk',
    kind: 'branch',
    active: true,
    last_login_at: TODAY,
    branch_id: 'b-senica',
    branch_name: 'Pobočka Senica',
    persons_count: 3,
    person: null,
  },
];
const ACCESS = [
  { mailbox_id: 'mb-senica', email: 'senica@smartsro.sk', read: true, send: true, own: true },
  { mailbox_id: 'mb-obj', email: 'objednavky.senica@smartsro.sk', read: true, send: true, own: false },
  { mailbox_id: 'mb-info', email: 'info@smartsro.sk', read: false, send: false, own: false },
];

async function open(page: Page, extra: Parameters<typeof mockApi>[1] = {}) {
  const calls: Record<string, unknown[]> = {};
  const record = (name: string, body: unknown) => (payload: unknown) => {
    (calls[name] ??= []).push(payload);
    return { body };
  };
  await mockApi(page, {
    'GET /api/auth/me': { body: ADMIN },
    'GET /api/auth/persons': { body: { ...ME_PICKER, persons: [ADMIN.person] } },
    'GET /api/settings/nav': { body: NAV },
    'GET /api/settings/admin/users': { body: USERS },
    'GET /api/settings/admin/branches': { body: [{ id: 'b-senica', name: 'Pobočka Senica', people: [] }] },
    'GET /api/settings/admin/users/a-senica/mailbox-access': { body: ACCESS },
    'PATCH /api/settings/admin/users/a-senica': record('patch', USERS[1]),
    'PUT /api/settings/admin/users/a-senica/mailbox-access': record('access', ACCESS),
    'POST /api/settings/admin/users/a-senica/logout-all': record('logout', { revoked_sessions: 2 }),
    ...extra,
  });
  await page.goto('/settings/users');
  await page.getByRole('button', { name: /^senica@smartsro\.sk/ }).click();
  return calls;
}

test('#55 W12-10 list, mailbox access, permission matrix and the save bar @mobile', async ({ page }, info) => {
  const calls = await open(page);
  await expect(page.getByRole('button', { name: /senica@smartsro\.sk Pobočkový · 3 osoby · dnes/ })).toBeVisible();
  const detail = page.getByTestId('user-detail');
  await expect(detail.getByRole('checkbox', { name: 'Čítať senica@smartsro.sk' })).toBeDisabled();
  await expect(page.getByTestId('permission-matrix')).toContainText('Správa nastavení, používateľov');
  await shot(page, `issue55-W12-10-${info.project.name}`);

  await detail.getByRole('checkbox', { name: 'Odosielať ako info@smartsro.sk' }).check();
  await expect(detail.getByRole('checkbox', { name: 'Čítať info@smartsro.sk' })).toBeChecked(); // send needs read
  await expect(detail.getByText('Neuložené zmeny')).toBeVisible();
  await detail.getByRole('button', { name: 'Uložiť' }).click();
  await expect
    .poll(() => calls.access?.at(-1))
    .toEqual([
      { mailbox_id: 'mb-obj', read: true, send: true },
      { mailbox_id: 'mb-info', read: true, send: true },
    ]);
  await expect.poll(() => calls.patch?.length).toBe(1);
});

test('#55 W12-10 „Overiť“ shows the server refusal; „Odhlásiť zo všetkých zariadení“ asks first @mobile', async ({
  page,
}, info) => {
  const calls = await open(page, {
    'POST /api/settings/admin/users/a-senica/verify': { status: 422, body: { detail: { code: 'verify_failed' } } },
  });
  const detail = page.getByTestId('user-detail');
  await detail.getByRole('button', { name: 'Overiť' }).click();
  const dialog = page.getByRole('dialog', { name: 'Overiť prihlásenie senica@smartsro.sk' });
  await dialog.getByLabel('Heslo schránky').fill('zle-heslo');
  await dialog.getByRole('button', { name: 'Overiť' }).click();
  await expect(detail).toContainText('Overenie zlyhalo: mailový server prihlásenie odmietol.');
  await shot(page, `issue55-W12-10-verify-${info.project.name}`);

  await detail.getByRole('button', { name: 'Odhlásiť zo všetkých zariadení' }).click();
  await page
    .getByRole('dialog', { name: 'Odhlásiť senica@smartsro.sk zo všetkých zariadení?' })
    .getByRole('button', { name: 'Odhlásiť zo všetkých zariadení' })
    .click();
  await expect(page.getByText('Odhlásené: 2 relácie.')).toBeVisible();
  expect(calls.logout).toHaveLength(1);
});

test('#55 W12-10 hides 2FA, Microsoft/Google and Vymazať (customer decision)', async ({ page }) => {
  await open(page);
  await expect(page.getByText('Vyžadovať 2FA')).toHaveCount(0);
  await expect(page.getByText('Prihlásenie cez Microsoft/Google')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Vymazať' })).toHaveCount(0);
});
