import { expect, ME, mockApi, shot, test } from './fixtures';

/** Issue #33: branch logins and persons are managed in Settings 10/11 without CLI or SQL. Fictional data. */
const ADMIN = { ...ME, person: { ...ME.person, role: 'admin' } };
const PICKER = {
  branch: null,
  email: ADMIN.email,
  persons: [ADMIN.person],
  current_person_id: ADMIN.person.id,
  last_person_id: null,
  idle_ask_minutes: null,
};
const NAV = {
  sections: [
    { id: '10', path: 'users', title: 'Používatelia a role', subs: [] },
    {
      id: '11',
      path: 'branches',
      title: 'Pobočky a osoby',
      subs: [
        { id: '11a', path: 'details', title: 'Údaje' },
        { id: '11b', path: 'people', title: 'Osoby' },
      ],
    },
  ],
};
const SENICA = 'b-senica';
const person = (id: string, first: string, last: string, fn: string, role: string, manager = false) => ({
  id,
  first_name: first,
  last_name: last,
  function: fn,
  role,
  is_manager: manager,
  active: true,
  phone: null,
  mobile: '+421 900 000 010',
  personal_email: null,
});
const branches = (linked: boolean) => [
  {
    id: SENICA,
    name: 'Pobočka Senica',
    address: null,
    phone: '+421 900 000 000',
    hours: 'Po–Pi 7:00–15:30',
    mailbox_id: 'mb-fa',
    mailbox_email: 'fa@smartsro.sk',
    login_account: { id: 'a-fa', email: 'fa@smartsro.sk', kind: linked ? 'branch' : 'personal', linked },
    signature_template_html: {},
    signature_images: [],
    people: [
      person('p-peter', 'Peter', 'Hudák', 'vedúci pobočky', 'admin', true),
      person('p-jana', 'Jana', 'Nováková', 'obchod', 'sales'),
      person('p-marek', 'Marek', 'Kováč', 'sklad', 'warehouse'),
    ],
  },
];
const USERS = [
  {
    id: 'a1',
    email: ADMIN.email,
    kind: 'personal',
    active: true,
    last_login_at: null,
    branch_id: null,
    branch_name: null,
    person: { id: 'p1', first_name: 'Jana', last_name: 'Testová', role: 'admin', active: true },
  },
  {
    id: 'a-fa',
    email: 'fa@smartsro.sk',
    kind: 'personal',
    active: true,
    last_login_at: null,
    branch_id: null,
    branch_name: null,
    person: { id: 'p-fa', first_name: 'Fa', last_name: '', role: 'viewer', active: true },
  },
];

async function mockAdmin(page: Parameters<typeof mockApi>[0], extra: Parameters<typeof mockApi>[1] = {}) {
  let linked = false;
  await mockApi(page, {
    'GET /api/auth/me': { body: ADMIN },
    'GET /api/auth/persons': { body: PICKER },
    'GET /api/settings/nav': { body: NAV },
    'GET /api/settings/admin/users': { body: USERS },
    'GET /api/settings/admin/branches': () => ({ body: branches(linked) }),
    'GET /api/settings/admin/mailboxes': { body: [{ id: 'mb-fa', email: 'fa@smartsro.sk' }] },
    [`POST /api/settings/admin/branches/${SENICA}/link-login`]: () => {
      linked = true;
      return { body: { ...USERS[1], kind: 'branch', branch_id: SENICA, branch_name: 'Pobočka Senica', person: null } };
    },
    ...extra,
  });
}

test('#33 W12-10 the only admin cannot be demoted: 409 last_admin is explained @mobile', async ({ page }, info) => {
  await mockAdmin(page, {
    'PATCH /api/settings/admin/users/a1': { status: 409, body: { detail: { code: 'last_admin' } } },
  });
  await page.goto('/settings/users');
  const detail = page.getByTestId('user-detail');
  await expect(detail.getByLabel('Prihlasovací e-mail')).toHaveValue(ADMIN.email);
  await detail.getByLabel('Rola').selectOption('sales');
  await detail.getByRole('button', { name: 'Uložiť' }).click();
  await expect(page.getByText('Aspoň jeden aktívny správca sa musí vedieť prihlásiť.')).toBeVisible();
  await shot(page, `issue33-W12-10-last-admin-${info.project.name}`);
});

test('#33 W12-10 "Zmeniť na prihlásenie pobočky" converts fa@ after a confirm', async ({ page }) => {
  let patched: unknown = null;
  await mockAdmin(page, {
    'PATCH /api/settings/admin/users/a-fa': (body) => {
      patched = body;
      return { body: { ...USERS[1], kind: 'branch', branch_id: SENICA, branch_name: 'Pobočka Senica', person: null } };
    },
  });
  await page.goto('/settings/users');
  await page.getByRole('button', { name: /fa@smartsro\.sk/ }).click();
  const detail = page.getByTestId('user-detail');
  await detail.getByRole('radio', { name: 'Pobočkový' }).click();
  await detail.getByLabel('Pobočka', { exact: true }).selectOption(SENICA);
  await shot(page, 'issue33-W12-10-branch-kind');
  await detail.getByRole('button', { name: 'Uložiť' }).click();
  const confirm = page.getByRole('dialog', { name: 'Zmeniť na prihlásenie pobočky' });
  await expect(confirm).toContainText('Doterajšia osoba sa deaktivuje');
  await confirm.getByRole('button', { name: 'Zmeniť' }).click();
  await expect.poll(() => patched).toMatchObject({ kind: 'branch', branch_id: SENICA });
});

test('#33 W12-10 create a branch login: branch is required', async ({ page }) => {
  await mockAdmin(page, {
    'POST /api/settings/admin/users': { status: 422, body: { detail: { code: 'branch_required' } } },
  });
  await page.goto('/settings/users');
  await page.getByRole('button', { name: 'Vytvoriť' }).click();
  const dialog = page.getByRole('dialog', { name: 'Nový prihlasovací účet' });
  await dialog.getByLabel('Prihlasovací e-mail').fill('nitra@smartsro.sk');
  await dialog.getByRole('radio', { name: 'Pobočkový' }).click();
  await dialog.getByRole('button', { name: 'Vytvoriť' }).click();
  await expect(dialog.getByText('Pobočkový účet potrebuje pobočku.')).toBeVisible();
  await shot(page, 'issue33-W12-10-create');
});

test('#33 W12-11a the branch mailbox login can be linked with the branch @mobile', async ({ page }, info) => {
  await mockAdmin(page);
  await page.goto('/settings/branches/details');
  const login = page.getByTestId('branch-login');
  await expect(login).toContainText('fa@smartsro.sk je teraz osobný účet');
  await expect(page.getByRole('button', { name: /Pridať pobočku/ })).toBeVisible();
  await shot(page, `issue33-W12-11a-${info.project.name}`);
  await login.getByRole('button', { name: 'Prepojiť prihlásenie s pobočkou' }).click();
  await expect(login).toContainText('je prihlásenie pobočky');
  await expect(login.getByRole('button')).toHaveCount(0);
});

test('#33 W12-11b persons table and drawer: edit and remove a person @mobile', async ({ page }, info) => {
  let saved: unknown = null;
  await mockAdmin(page, {
    'PUT /api/settings/admin/people/p-jana': (body) => {
      saved = body;
      return { body: { id: 'p-jana', active: true, role: 'sales' } };
    },
    'DELETE /api/settings/admin/people/p-marek': { body: { id: 'p-marek', result: 'deactivated' } },
  });
  await page.goto('/settings/branches/people');
  await expect(page.getByRole('cell', { name: 'Peter Hudák' })).toBeVisible();
  await shot(page, `issue33-W12-11b-${info.project.name}`);

  await page.getByRole('button', { name: 'Jana Nováková' }).click();
  const drawer = page.getByTestId('person-drawer');
  await drawer.getByLabel('Funkcia').fill('vedúca predaja');
  await drawer.getByRole('switch', { name: 'Vedúci pobočky' }).click();
  await shot(page, `issue33-W12-11b-drawer-${info.project.name}`);
  await drawer.getByRole('button', { name: 'Uložiť' }).click();
  await expect.poll(() => saved).toMatchObject({ function: 'vedúca predaja', is_manager: true });

  await page.getByRole('button', { name: 'Marek Kováč' }).click();
  await page.getByTestId('person-drawer').getByRole('button', { name: 'Odstrániť osobu' }).click();
  await page
    .getByRole('dialog', { name: 'Odstrániť osobu Marek Kováč' })
    .getByRole('button', { name: 'Odstrániť osobu' })
    .click();
  await expect(page.getByText('Osoba má históriu – bola deaktivovaná.')).toBeVisible();
});
