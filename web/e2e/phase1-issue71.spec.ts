import { expect, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

/** Issue #71: the person of a personal login (eshop@) in Pobočky a osoby › Osobné účty, with the branch for the
 * signature. Fictional data. */
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
      ],
    },
  ],
};
const BRANCHES = [
  {
    id: 'b-senica',
    name: 'Pobočka Senica',
    address: 'Hlavná 1, 905 01 Senica',
    phone: '+421 900 000 000',
    mailbox_email: 'senica@smartsro.sk',
    login_account: null,
    signature_template_html: {},
    signature_images: [],
    people: [
      {
        id: 'p-jana',
        first_name: 'Jana',
        last_name: 'Nováková',
        function: 'obchod',
        role: 'sales',
        is_manager: true,
        active: true,
        phone: null,
        mobile: null,
        personal_email: null,
      },
    ],
  },
];
const ESHOP = {
  id: 'p-eshop',
  first_name: 'Eshop',
  last_name: '',
  function: null,
  role: 'sales',
  is_manager: false,
  active: true,
  phone: null,
  mobile: null,
  personal_email: null,
  login_email: 'eshop@smartsro.sk',
  branch_id: null as string | null,
};

test('#71 W12-11b admin edits the eshop@ person and picks its branch for the signature @mobile', async ({
  page,
}, info) => {
  const saved: Record<string, unknown>[] = [];
  let eshop = { ...ESHOP };
  await mockApi(page, {
    'GET /api/auth/me': { body: ADMIN },
    'GET /api/auth/persons': { body: { ...ME_PICKER, persons: [ADMIN.person] } },
    'GET /api/settings/nav': { body: NAV },
    'GET /api/settings/admin/branches': { body: BRANCHES },
    'GET /api/settings/admin/personal-people': () => ({ body: [eshop] }),
    'PUT /api/settings/admin/people/p-eshop': (body) => {
      saved.push(body as Record<string, unknown>);
      eshop = { ...eshop, ...(body as object) };
      return { body: { id: 'p-eshop', active: true, role: 'sales' } };
    },
  });
  await page.goto('/settings/branches/people');
  const section = page.getByTestId('personal-people');
  await expect(section.getByRole('heading', { name: 'Osobné účty' })).toBeVisible();
  await expect(section.getByRole('cell', { name: 'eshop@smartsro.sk' })).toBeVisible();
  await expect(section.getByRole('cell', { name: 'bez pobočky' })).toBeVisible();

  await section.getByRole('button', { name: 'Eshop' }).click();
  const drawer = page.getByTestId('person-drawer');
  await drawer.getByLabel('Priezvisko').fill('Smart');
  await drawer.getByLabel('Funkcia').fill('e-shop');
  await drawer.getByLabel('Pobočka (pre podpis)').selectOption({ label: 'Pobočka Senica' });
  // a personal login has no manager flag and is never removed from here
  await expect(drawer.getByRole('switch', { name: 'Vedúci pobočky' })).toHaveCount(0);
  await expect(drawer.getByRole('button', { name: 'Odstrániť osobu' })).toHaveCount(0);
  await shot(page, `issue71-W12-11b-personal-drawer-${info.project.name}`);
  await drawer.getByRole('button', { name: 'Uložiť' }).click();
  await expect
    .poll(() => saved.at(-1))
    .toMatchObject({ first_name: 'Eshop', last_name: 'Smart', function: 'e-shop', branch_id: 'b-senica' });
  await expect(section.getByRole('cell', { name: 'Pobočka Senica' })).toBeVisible();
  await shot(page, `issue71-W12-11b-personal-${info.project.name}`);
});

test('#71 W12-11b a branch person drawer sends no branch_id', async ({ page }) => {
  const saved: Record<string, unknown>[] = [];
  await mockApi(page, {
    'GET /api/auth/me': { body: ADMIN },
    'GET /api/auth/persons': { body: { ...ME_PICKER, persons: [ADMIN.person] } },
    'GET /api/settings/nav': { body: NAV },
    'GET /api/settings/admin/branches': { body: BRANCHES },
    'PUT /api/settings/admin/people/p-jana': (body) => {
      saved.push(body as Record<string, unknown>);
      return { body: { id: 'p-jana', active: true, role: 'sales' } };
    },
  });
  await page.goto('/settings/branches/people');
  await expect(page.getByTestId('personal-people')).toHaveCount(0);
  await page.getByRole('button', { name: 'Upraviť osobu Jana Nováková' }).click();
  const drawer = page.getByTestId('person-drawer');
  await expect(drawer.getByLabel('Pobočka (pre podpis)')).toHaveCount(0);
  await drawer.getByRole('button', { name: 'Uložiť' }).click();
  await expect.poll(() => saved.length).toBe(1);
  expect(saved[0]).not.toHaveProperty('branch_id');
});
