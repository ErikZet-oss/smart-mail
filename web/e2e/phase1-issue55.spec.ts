import type { Page } from '@playwright/test';

import { expect, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

/** Issue #55: Settings 11 Pobočky a osoby as in Figma W12-11a `68:60641`, W12-11b `68:61587` / drawer `68:61806`,
 * W12-11d `72:62234`. Fictional data. */
const ADMIN = { ...ME, person: { ...ME.person, role: 'admin' } };
const NAV = {
  sections: [
    {
      id: '11',
      path: 'branches',
      title: 'Pobočky a osoby',
      subs: [
        { id: '11a', path: 'details', title: 'Údaje' },
        { id: '11b', path: 'people', title: 'Osoby' },
        { id: '11c', path: 'signature', title: 'Podpis' },
        { id: '11d', path: 'login', title: 'Prihlasovanie' },
        { id: '11e', path: 'money', title: 'Money' },
      ],
    },
  ],
};
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
  photo_url: null as string | null,
  cover_branch_ids: [] as string[],
});
const branch = (id: string, name: string, mailbox: string, people: ReturnType<typeof person>[]) => ({
  id,
  name,
  address: null,
  phone: '+421 900 000 000',
  hours: 'Po–Pi 7:00–15:30',
  mailbox_id: `mb-${id}`,
  mailbox_email: `${mailbox}@smartsro.sk`,
  login_account: { id: `a-${id}`, email: `${mailbox}@smartsro.sk`, kind: 'branch', linked: true },
  idle_ask_minutes: null,
  remember_days: 30,
  logo_url: null as string | null,
  folder_ids: [] as string[],
  signature_template_html: {},
  signature_images: [],
  people,
});
const BRANCHES = () => [
  branch('b-trnava', 'Pobočka Trnava', 'trnava', [person('p-ivan', 'Ivan', 'Ďurica', 'vedúci pobočky', 'sales', true)]),
  branch('b-senica', 'Pobočka Senica', 'senica', [
    person('p-peter', 'Peter', 'Hudák', 'vedúci pobočky', 'admin', true),
    person('p-jana', 'Jana', 'Nováková', 'obchod', 'sales'),
    person('p-marek', 'Marek', 'Kováč', 'sklad', 'warehouse'),
  ]),
];
const PNG = Buffer.from(
  '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082',
  'hex',
);

async function open(page: Page, path: string, extra: Parameters<typeof mockApi>[1] = {}) {
  const calls: { method: string; url: string; body: unknown }[] = [];
  const record =
    (method: string, url: string, body: unknown = { ok: true }) =>
    (payload: unknown) => {
      calls.push({ method, url, body: payload });
      return { body };
    };
  await mockApi(page, {
    'GET /api/auth/me': { body: ADMIN },
    'GET /api/auth/persons': { body: { ...ME_PICKER, persons: [ADMIN.person] } },
    'GET /api/settings/nav': { body: NAV },
    'GET /api/settings/admin/branches': () => ({ body: BRANCHES() }),
    'GET /api/settings/admin/mailboxes': {
      body: [
        { id: 'mb-b-senica', email: 'senica@smartsro.sk' },
        { id: 'mb-b-trnava', email: 'trnava@smartsro.sk' },
      ],
    },
    'GET /api/settings/admin/branch-folders': {
      body: [
        { id: 'f-eshop-senica', name: 'Senica', mailbox_email: 'eshop@smartsro.sk' },
        { id: 'f-info-senica', name: 'Senica', mailbox_email: 'info@smartsro.sk' },
      ],
    },
    'PUT /api/settings/admin/people/p-jana': record('PUT', 'p-jana', { id: 'p-jana', active: true, role: 'sales' }),
    'PUT /api/settings/admin/people/p-marek': record('PUT', 'p-marek', {
      id: 'p-marek',
      active: false,
      role: 'warehouse',
    }),
    'PUT /api/settings/admin/branches/b-trnava': record('PUT', 'b-trnava', { id: 'b-trnava' }),
    'POST /api/settings/admin/people/p-jana/photo': record('POST', 'photo', { photo_url: '/logo-smart.svg' }),
    'POST /api/settings/admin/branches/b-trnava/logo': record('POST', 'logo', { logo_url: '/logo-smart.svg' }),
    ...extra,
  });
  await page.goto(path);
  return calls;
}

test('#55 W12-11b rows open the drawer by click, Enter and the pencil; Aktívna is a switch @mobile', async ({
  page,
}, info) => {
  const calls = await open(page, '/settings/branches/people');
  await page.getByRole('button', { name: /^Pobočka Senica/ }).click();
  await expect(page.getByRole('heading', { name: 'Pobočka Senica', level: 1 })).toBeVisible();
  await expect(page.getByRole('tab', { name: 'Osoby 3' })).toBeVisible();
  await shot(page, `issue55-W12-11b-${info.project.name}`);

  const rows = page.getByTestId('person-row');
  await rows.filter({ hasText: 'Peter Hudák' }).click();
  const drawer = page.getByTestId('person-drawer');
  await expect(drawer.getByRole('heading', { name: 'Peter Hudák' })).toBeVisible();
  await drawer.getByRole('button', { name: 'Zrušiť' }).click();

  await rows.filter({ hasText: 'Marek Kováč' }).focus();
  await page.keyboard.press('Enter');
  await expect(drawer.getByRole('heading', { name: 'Marek Kováč' })).toBeVisible();
  await drawer.getByRole('button', { name: 'Zrušiť' }).click();

  await page.getByRole('button', { name: 'Upraviť osobu Jana Nováková' }).click();
  await expect(drawer.getByRole('heading', { name: 'Jana Nováková' })).toBeVisible();
  await drawer.getByRole('button', { name: 'Zrušiť' }).click();

  await page.getByRole('switch', { name: 'Aktívna – Marek Kováč' }).click();
  await expect.poll(() => calls.find((c) => c.url === 'p-marek')?.body).toMatchObject({ active: false });
  await expect(drawer).toHaveCount(0); // the switch does not open the drawer
});

test('#55 W12-11b drawer: photo upload and „Pôsobí aj na pobočkách“ @mobile', async ({ page }, info) => {
  const calls = await open(page, '/settings/branches/people');
  await page.getByRole('button', { name: /^Pobočka Senica/ }).click();
  await page.getByRole('button', { name: 'Upraviť osobu Jana Nováková' }).click();
  const drawer = page.getByTestId('person-drawer');
  await drawer
    .getByTestId('person-photo-input')
    .setInputFiles({ name: 'jana.png', mimeType: 'image/png', buffer: PNG });
  await expect.poll(() => calls.some((c) => c.url === 'photo')).toBe(true);
  await expect(drawer.getByRole('button', { name: 'Odstrániť fotku' })).toBeVisible();
  await drawer.getByRole('button', { name: '+ pridať' }).click();
  await drawer.getByRole('combobox', { name: 'Pôsobí aj na pobočkách' }).selectOption({ label: 'Pobočka Trnava' });
  await expect(drawer.getByRole('button', { name: 'Odstrániť Pobočka Trnava' })).toBeVisible();
  await expect(drawer.getByText('Obchodník v Money')).toHaveCount(0); // Phase 3
  await shot(page, `issue55-W12-11b-drawer-${info.project.name}`);
  await drawer.getByRole('button', { name: 'Uložiť' }).click();
  await expect
    .poll(() => calls.find((c) => c.url === 'p-jana')?.body)
    .toMatchObject({ cover_branch_ids: ['b-trnava'] });
});

test('#55 W12-11a Údaje: logo, branch folders and the Uložiť / Zrušiť bar @mobile', async ({ page }, info) => {
  const calls = await open(page, '/settings/branches/details');
  const form = page.getByTestId('branch-details');
  await expect(form.getByLabel('Názov pobočky')).toHaveValue('Pobočka Trnava');
  await form.getByTestId('branch-logo-input').setInputFiles({ name: 'logo.png', mimeType: 'image/png', buffer: PNG });
  await expect.poll(() => calls.some((c) => c.url === 'logo')).toBe(true);
  await form.getByRole('button', { name: '+ pridať' }).click();
  await form.getByRole('combobox', { name: 'Priečinky pobočky' }).selectOption({ label: 'eshop@ › Senica' });
  await expect(form.getByRole('button', { name: 'Odstrániť eshop@ › Senica' })).toBeVisible();
  await shot(page, `issue55-W12-11a-${info.project.name}`);
  await form.getByRole('button', { name: 'Uložiť' }).click();
  await expect
    .poll(() => calls.find((c) => c.url === 'b-trnava')?.body)
    .toMatchObject({ name: 'Pobočka Trnava', folder_ids: ['f-eshop-senica'] });

  await form.getByLabel('Otváracie hodiny').fill('zmenené');
  await form.getByRole('button', { name: 'Zrušiť' }).click();
  await expect(form.getByLabel('Otváracie hodiny')).toHaveValue('Po–Pi 7:00–15:30');
});

test('#55 W12-11d Prihlasovanie saves idle ask and remember days @mobile', async ({ page }, info) => {
  const calls = await open(page, '/settings/branches/login');
  const tab = page.getByTestId('branch-login-settings');
  await tab.getByLabel('Opýtať sa „Kto ste?“ po nečinnosti').selectOption({ label: '60 min' });
  await tab.getByLabel('Zostať prihlásený na zariadení').selectOption({ label: '7 dní' });
  await shot(page, `issue55-W12-11d-${info.project.name}`);
  await tab.getByRole('button', { name: 'Uložiť' }).click();
  await expect
    .poll(() => calls.find((c) => c.url === 'b-trnava')?.body)
    .toMatchObject({ idle_ask_minutes: 60, remember_days: 7 });
});

test('#55 „Vymazať pobočku“ explains a branch with people and deletes an empty one', async ({ page }) => {
  let reply: { status: number; body: unknown } = {
    status: 409,
    body: { detail: { code: 'branch_has_people', count: 1 } },
  };
  await open(page, '/settings/branches/details', {
    'DELETE /api/settings/admin/branches/b-trnava': () => reply,
  });
  await page.getByRole('button', { name: 'Vymazať pobočku' }).click();
  const confirm = page.getByRole('dialog', { name: 'Vymazať pobočku Pobočka Trnava?' });
  await confirm.getByRole('button', { name: 'Vymazať pobočku' }).click();
  await expect(page.getByText('Pobočka má aktívne osoby. Najprv ich presuňte alebo deaktivujte.')).toBeVisible();

  reply = { status: 200, body: { id: 'b-trnava', result: 'deleted' } };
  await page.getByRole('button', { name: 'Vymazať pobočku' }).click();
  await page
    .getByRole('dialog', { name: 'Vymazať pobočku Pobočka Trnava?' })
    .getByRole('button', { name: 'Vymazať pobočku' })
    .click();
  await expect(page.getByText('Pobočka bola vymazaná.')).toBeVisible();
});
