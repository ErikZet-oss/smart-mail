import { expect, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

// Phase 4a — W6e Dodacie listy prijaté (Figma 46:41526, M13 85:3245) and W6u Nahrať doklad (46:42624). Fictional data.

const WAREHOUSE = { ...ME, person: { ...ME.person, role: 'warehouse' } };
const doc = (n: number, extra: Record<string, unknown> = {}) => ({
  id: `d-${n}`,
  source: n === 1 ? 'mail' : 'upload',
  kind: 'invoice',
  status: n === 1 ? 'missing_data' : 'needs_review',
  filename: `FA-${n}.pdf`,
  branch_id: 'b-se',
  branch_name: 'Senica',
  centre_code: '20',
  warehouse_code: '20',
  supplier_name: n === 1 ? 'Fiktívny dodávateľ s.r.o.' : 'Fiktívne spojovacie s.r.o.',
  supplier_ico: '12345678',
  supplier_money_id: null,
  doc_number: `FA-2026-0045${n}`,
  doc_date: '2026-10-28',
  currency: 'EUR',
  total: n === 1 ? '650.79' : '1204.5',
  lines: n === 1 ? 7 : 14,
  blocking: n === 1 ? 1 : 0,
  warnings: 0,
  error: null,
  created_at: '2026-10-31T08:00:00Z',
  ...extra,
});
const BASE = {
  'GET /api/auth/me': { body: WAREHOUSE },
  'GET /api/auth/persons': { body: { ...ME_PICKER, persons: [WAREHOUSE.person] } },
  'GET /api/system/info': { body: { admin_contact_email: null, features: { money: true } } },
};

test('4a W6e: supplier documents before any Money write @mobile', async ({ page }, info) => {
  await mockApi(page, { ...BASE, 'GET /api/purchasing/documents': { body: { items: [doc(1), doc(2)], total: 2 } } });
  await page.goto('/docs');
  await expect(page).toHaveURL(/\/docs\/delivery-notes$/); // W6 → first allowed tab of a warehouse person
  const list = page.getByTestId('documents-list');
  await expect(list).toContainText('Fiktívny dodávateľ s.r.o.');
  await expect(list).toContainText('FA-2026-00451');
  await expect(list).toContainText('Chýbajú údaje');
  await expect(list).toContainText('650,79 €');
  if (info.project.name === 'desktop') {
    await expect(list).toContainText('nový – návrh');
    await expect(list).toContainText('pri zápise');
  }
  const tabs = page.getByRole('navigation', { name: 'Doklady' });
  await expect(tabs.getByRole('link', { name: /Dodacie listy/ })).toHaveAttribute('aria-current', 'page');
  await expect(tabs.getByRole('link', { name: 'Upomienky' })).toHaveCount(0); // not a warehouse tab
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  await shot(page, `phase4a-W6e-${info.project.name}`);
});

test('4a W6u: upload a supplier document from the Doklady header', async ({ page }, info) => {
  let uploaded = false;
  await mockApi(page, {
    ...BASE,
    'GET /api/purchasing/documents': () => ({ body: { items: uploaded ? [doc(2)] : [], total: uploaded ? 1 : 0 } }),
    'POST /api/purchasing/documents': () => {
      uploaded = true;
      return { body: doc(2) };
    },
  });
  await page.goto('/docs/delivery-notes');
  await expect(page.getByText('Žiadne dodacie listy na kontrolu')).toBeVisible();
  await page.getByRole('button', { name: 'Nahrať doklad' }).click();
  const dialog = page.getByRole('dialog', { name: 'Nahrať doklad' });
  await expect(dialog.getByRole('button', { name: 'Nahrať', exact: true })).toBeDisabled();
  await dialog.getByLabel('Vybrať súbor').setInputFiles({
    name: 'FA-2026-00452.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4 fictional'),
  });
  await expect(dialog.getByTestId('upload-file')).toHaveText('FA-2026-00452.pdf');
  await expect(dialog.getByText('Objednávka zákazníka')).toBeVisible(); // customer orders come with 4d (disabled)
  await shot(page, `phase4a-W6u-${info.project.name}`);
  await dialog.getByRole('button', { name: 'Nahrať', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByTestId('documents-list')).toContainText('Fiktívne spojovacie s.r.o.');
});

test('4a W6e: a sales person has no Dodacie listy tab and no upload', async ({ page }) => {
  const SALES = { ...ME, person: { ...ME.person, role: 'sales' } };
  await mockApi(page, {
    ...BASE,
    'GET /api/auth/me': { body: SALES },
    'GET /api/auth/persons': { body: { ...ME_PICKER, persons: [SALES.person] } },
    'GET /api/money/reminders': { body: [] },
    'GET /api/money/reminders/history': { body: [] },
  });
  await page.goto('/docs');
  await expect(page).toHaveURL(/\/docs\/reminders$/);
  await expect(page.getByRole('button', { name: 'Nahrať doklad' })).toBeDisabled();
  await expect(
    page.getByRole('navigation', { name: 'Doklady' }).getByRole('link', { name: 'Dodacie listy' }),
  ).toHaveCount(0);
});
