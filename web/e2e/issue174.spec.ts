import { expect, ME, ME_PICKER, mockApi, test } from './fixtures';

/** #174 W12-11e Money (pobočka): centre + own SK print reports, „Vyskúšať PDF“. Fictional data only. */
const ADMIN = { ...ME, person: { ...ME.person, role: 'admin' } };
const NAV = {
  sections: [
    {
      id: '11',
      path: 'branches',
      title: 'Pobočky a osoby',
      subs: [
        { id: '11a', path: 'details', title: 'Údaje' },
        { id: '11e', path: 'money', title: 'Money' },
      ],
    },
  ],
};
const BRANCH = {
  id: 'b-nitra',
  name: 'Pobočka Nitra',
  address: null,
  phone: null,
  hours: null,
  mailbox_id: null,
  mailbox_email: null,
  login_account: null,
  idle_ask_minutes: null,
  remember_days: 30,
  logo_url: null,
  folder_ids: [],
  signature_template_html: {},
  signature_images: [],
  people: [],
};
const CENTRE = '30303030-3030-4030-8030-303030303030';

test('#174 W12-11e: centre from Money, branch report ids, validation, save', async ({ page }) => {
  const saved: unknown[] = [];
  await mockApi(page, {
    'GET /api/auth/me': { body: ADMIN },
    'GET /api/auth/persons': { body: { ...ME_PICKER, persons: [ADMIN.person] } },
    'GET /api/system/info': { body: { admin_contact_email: null, features: { money: true } } },
    'GET /api/system/maintenance': { body: { active: false, until: null } },
    'GET /api/settings/nav': { body: NAV },
    'GET /api/settings/admin/branches': { body: [BRANCH] },
    'GET /api/settings/money/branches': {
      body: {
        centres: [
          { id: CENTRE, code: '30', name: 'Nitra' },
          { id: '20202020-2020-4020-8020-202020202020', code: '20', name: 'Senica' },
        ],
        branches: [
          {
            id: 'b-nitra',
            name: 'Pobočka Nitra',
            centre_id: CENTRE,
            centre_missing: false,
            reports: { invoice: '77', proforma: '' },
          },
        ],
      },
    },
    'PUT /api/settings/money/branches/b-nitra': (payload) => {
      saved.push(payload);
      return { body: { id: 'b-nitra', name: 'Pobočka Nitra', centre_id: CENTRE, centre_missing: false, reports: {} } };
    },
  });
  await page.goto('/settings/branches/money');
  const panel = page.getByTestId('settings-branch-money');
  await expect(panel.getByLabel('Stredisko (číslo pobočky)')).toHaveValue(CENTRE);
  const proforma = panel.getByLabel('Tlačová zostava – zálohová faktúra (SK)');
  await expect(panel.getByLabel('Tlačová zostava – faktúra vydaná (SK)')).toHaveValue('77');
  await proforma.fill('1 OR 1');
  await expect(panel.getByText('ID zostavy je GUID alebo číslo konfigurácie zostavy.')).toBeVisible();
  await expect(panel.getByRole('button', { name: 'Uložiť' })).toBeDisabled();
  await proforma.fill('78');
  await panel.getByRole('button', { name: 'Uložiť' }).click();
  await expect.poll(() => saved).toEqual([{ centre_id: CENTRE, reports: { invoice: '77', proforma: '78' } }]);
  await expect(panel).toContainText('Prázdne = firemná zostava z Nastavenia › Money S4 › Tlačové zostavy.');
});
