import { expect, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

// Phase 4b-3 — W12-14 Nastavenia › Nákup a sklad (Figma 75:68205, chyba 75:68435, uložené 75:68866). Fictional data.

const ADMIN = { ...ME, person: { ...ME.person, role: 'admin' } };
const NAV = { sections: [{ id: '14', path: 'purchasing', title: 'Nákup a sklad', subs: [] }] };
const SETTINGS = {
  price_diff_pct: '10',
  qty_diff_pct: '0',
  confirm_roles: ['warehouse', 'admin'],
  issue_date: 'supplier',
  warehouse_rules: [],
  branch_warehouses: ['10 Trnava', '20 Senica'],
  warehouses: [
    { id: 'w-20', label: '20 – Senica' },
    { id: 'w-99', label: '99 – Externý sklad' },
  ],
  suppliers: [{ id: 's-1', label: 'Fiktívny dodávateľ s.r.o.' }],
};
const MAPPING = {
  id: 'm-1',
  supplier_id: 's-1',
  supplier_name: 'Fiktívny dodávateľ s.r.o.',
  code: 'FX-933-1030-A2',
  article_id: 'a-1',
  article_name: 'skr. M10 x30 A2 DIN 933',
  unit_factor: '200',
  confirmed_by: 'Marek K.',
  confirmed_at: '2026-10-09T08:00:00Z',
  uses_count: 6,
};

test('4b-3 W12-14: info rows, thresholds, roles, warehouse rule, learned codes', async ({ page }, info) => {
  let saved: Record<string, unknown> | null = null;
  let deleted = false;
  await mockApi(page, {
    'GET /api/auth/me': { body: ADMIN },
    'GET /api/auth/persons': { body: { ...ME_PICKER, persons: [ADMIN.person] } },
    'GET /api/system/info': { body: { admin_contact_email: null, features: { money: true } } },
    'GET /api/system/maintenance': { body: { active: false, until: null } },
    'GET /api/settings/nav': { body: NAV },
    'GET /api/settings/purchasing': { body: SETTINGS },
    'PUT /api/settings/purchasing': (body) => {
      saved = body as Record<string, unknown>;
      return { body: { ...SETTINGS, ...saved } };
    },
    'GET /api/settings/purchasing/mappings': () => ({
      body: deleted ? { items: [], total: 0 } : { items: [MAPPING], total: 1 },
    }),
    'DELETE /api/settings/purchasing/mappings/m-1': () => {
      deleted = true;
      return { status: 204, body: null };
    },
  });
  await page.goto('/settings/purchasing');
  const panel = page.getByTestId('settings-purchasing');
  await expect(panel).toContainText('Len dodací list prijatý – faktúru prijatú Smart Mail nerieši (D7).');
  await expect(panel).toContainText('(10 Trnava, 20 Senica)');
  await expect(page.getByTestId('mapping-FX-933-1030-A2')).toContainText('1 : 200');
  await expect(page.getByTestId('mapping-FX-933-1030-A2')).toContainText('6×');
  await expect(page.getByTestId('purchasing-export')).toHaveAttribute('href', '/api/settings/purchasing/mappings.csv');
  await expect(page.getByTestId('purchasing-save')).toBeDisabled();
  await shot(page, `phase4b-W12-14-${info.project.name}`);

  // validation state (chyba)
  const price = page.getByRole('textbox', { name: 'Upozorniť na odchýlku ceny nad' });
  await price.fill('150');
  await expect(panel.getByText('Zadajte číslo 0 – 100.')).toBeVisible();
  await expect(page.getByTestId('purchasing-save')).toBeDisabled();
  await page.getByRole('button', { name: 'Sklad', exact: false, pressed: true }).first().click();
  await page.getByRole('button', { name: /Správca/, pressed: true }).click();
  await expect(panel.getByText('Vyberte aspoň jednu rolu.')).toBeVisible();

  await price.fill('20');
  await page.getByRole('button', { name: /Správca/ }).click();
  await page.getByRole('radio', { name: 'Dátum schválenia' }).click();
  await page.getByRole('button', { name: 'Pridať pravidlo' }).click();
  await page.getByLabel('Dodávateľ', { exact: true }).selectOption('s-1');
  await page.getByLabel('Sklad', { exact: true }).selectOption('w-99');
  await page.getByTestId('purchasing-save').click();
  await expect(page.getByText('Nastavenia uložené.')).toBeVisible();
  expect(saved).toMatchObject({
    price_diff_pct: '20',
    confirm_roles: ['admin'],
    issue_date: 'approval',
    warehouse_rules: [{ supplier_money_id: 's-1', warehouse_id: 'w-99' }],
  });

  await page.getByRole('button', { name: 'Zmazať' }).click();
  await page.getByTestId('mapping-delete-confirm').click();
  await expect(page.getByText('Zatiaľ žiadne naučené kódy.', { exact: false })).toBeVisible();
});
