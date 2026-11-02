import { expect, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

// Phase 4b — W6h Dodací list prijatý – karta (Figma 43:38227, drawer 44:37979, M13b 85:3565 / 85:3615).
// Read-only: „Vytvoriť v Money“ stays disabled until 4c. All companies, articles and prices are fictional.

const WAREHOUSE = { ...ME, person: { ...ME.person, role: 'warehouse' } };
const art = (name: string, catalog: string, ean: string | null) => ({ code: null, catalog, name, ean, unit: 'ks' });
const line = (n: number, extra: Record<string, unknown>) => ({
  line_no: n,
  supplier_code: `FX-${n}`,
  ean: null,
  name: `Text dodávateľa ${n}`,
  qty: '1000',
  unit: 'ks',
  unit_price: '0.0612',
  vat_rate: '23',
  line_total: '61.20',
  is_fee: false,
  line_status: 'matched',
  article_id: `a-${n}`,
  match_method: 'supplier_code',
  unit_factor: '1.000000',
  warehouse_id: 'w-20',
  warehouse_code: '20',
  candidates: [],
  article: art(`skr. M10 x30 A2 DIN 933 (${n})`, `30990301003${n}`, `859400123010${n}`),
  qty_our: '1000.0000',
  price_our: '0.0612',
  ...extra,
});
const UNMATCHED = line(3, {
  supplier_code: 'FX-7380-0616-A2',
  name: 'Šroub ISO 7380 M6x16 A2 TX',
  line_status: 'unmatched',
  article_id: null,
  match_method: 'none',
  unit_factor: null,
  warehouse_id: null,
  warehouse_code: null,
  article: null,
  qty_our: null,
  price_our: null,
  candidates: [
    { article_id: 'a-7380', code: null, catalog: '309973800616', name: 'skr. ISO 7380 M6 x16 A2 TX', unit: 'ks' },
  ],
});
const detail = (lines: unknown[], status = 'missing_data', version = 3) => ({
  id: 'd-1',
  source: 'mail',
  kind: 'invoice',
  status,
  filename: 'FA-2611452.pdf',
  branch_id: 'b-se',
  branch_name: 'Senica',
  centre_code: '20',
  warehouse_code: '20',
  supplier_name: 'Fiktívny dodávateľ s.r.o.',
  supplier_ico: '27654321',
  supplier_money_id: 's-1',
  doc_number: '2611452',
  doc_date: '2026-10-20',
  currency: 'EUR',
  total: '668.00',
  lines: 4,
  blocking: status === 'missing_data' ? 1 : 0,
  warnings: 1,
  error: null,
  created_at: '2026-10-31T08:00:00Z',
  delivery_note_number: 'DL-2026-04417',
  order_reference: null,
  vat_recap: [{ rate: '23', base: '668.00', vat: '0.00' }],
  fees: [{ name: 'Doprava', amount: '12.50' }],
  extract_method: 'pdf_llm',
  field_confidence: {},
  checks: [
    ...(status === 'missing_data' ? [{ id: 'DL-B4', level: 'blocking', params: { n: 1, lines: [3] } }] : []),
    { id: 'DL-W1', level: 'warning', params: { line: 1, x: '15.0', last: '0.0532' } },
  ],
  message_id: null,
  version,
  money_available: true,
  supplier: { name: 'Fiktívny dodávateľ s.r.o.', ico: '27654321', dic: 'CZ27654321', icdph: 'CZ27654321' },
  series: 'DLP SE',
  template: { predkontace: 'FP010', druh_pohybu: 'obstaranie', druh_skladoveho_pohybu: 'príjem' },
  warehouses: [
    { id: 'w-20', code: '20', name: 'Senica' },
    { id: 'w-99', code: '99', name: 'Externý sklad' },
  ],
  items: [
    ...lines,
    { ...line(4, {}), is_fee: true, name: 'Doprava', line_status: 'unmatched', match_method: null, article: null },
  ],
});
const BASE = {
  'GET /api/auth/me': { body: WAREHOUSE },
  'GET /api/auth/persons': { body: { ...ME_PICKER, persons: [WAREHOUSE.person] } },
  'GET /api/system/info': { body: { admin_contact_email: null, features: { money: true } } },
};

test('4b W6h: Money card, matching status, line drawer with candidate → matched @mobile', async ({ page }, info) => {
  const mobile = info.project.name !== 'desktop';
  let sent: Record<string, unknown> | null = null;
  const before = detail([line(1, {}), line(2, { match_method: 'learned' }), UNMATCHED]);
  await mockApi(page, {
    ...BASE,
    'GET /api/purchasing/documents/d-1': { body: before },
    'POST /api/purchasing/documents/d-1/lines/3/article': (body) => {
      sent = body as Record<string, unknown>;
      return {
        body: detail(
          [
            line(1, {}),
            line(2, { match_method: 'learned' }),
            line(3, { match_method: 'user', article: art('skr. ISO 7380 M6 x16 A2 TX', '309973800616', null) }),
          ],
          'needs_review',
          4,
        ),
      };
    },
    'GET /api/purchasing/articles': { body: [] },
  });
  await page.goto('/docs/delivery-notes/d-1');
  await expect(page.getByTestId('screen-w6h')).toBeVisible();
  await expect(page.getByTestId('w6h-status')).toHaveText('Chýbajú údaje');
  await expect(page.getByRole('button', { name: 'Vytvoriť v Money' })).toBeDisabled(); // 4c
  if (mobile) {
    await expect(page.getByTestId('m13b')).toContainText('DL-2026-04417');
    await expect(page.getByTestId('m13b')).toContainText('FP010');
    await expect(page.getByTestId('m13b-summary')).toContainText('1 nespárovaných');
    await shot(page, `phase4b-M13b-${info.project.name}`);
    await page.getByTestId('m13b-line-3').click();
  } else {
    const header = page.getByTestId('w6h-header');
    await expect(header).toContainText('bude pridelené');
    await expect(header).toContainText('DLP SE');
    await expect(header).toContainText('pri zápise do Money'); // D13
    await expect(page.getByTestId('w6h-supplier')).toContainText('CZ27654321');
    await expect(page.getByTestId('w6h-supplier').getByText('DIČ', { exact: true })).toBeInViewport();
    const grid = page.getByTestId('w6h-grid');
    await expect(grid).toContainText('309903010031'); // our catalog number of the Money article
    await expect(grid).toContainText('1 000,0000'); // Money number format
    await expect(page.getByTestId('w6h-line-3')).toContainText('Šroub ISO 7380'); // unmatched shows supplier text
    await expect(page.getByTestId('w6h-sum')).toHaveText('183,60');
    await page.getByTestId('w6h-checks-toggle').click();
    await expect(page.getByTestId('check-DL-B4')).toContainText('1 riadkov nie je spárovaných.');
    await shot(page, `phase4b-W6h-${info.project.name}`);
    await page.getByTestId('w6h-checks-toggle').click();
    await page.getByRole('button', { name: /Poplatky/ }).click();
    await expect(page.getByTestId('w6h-fees')).toContainText('Poplatky sa nezapisujú');
    await page.getByRole('button', { name: /Položky/ }).click();
    await page.getByTestId('w6h-line-3').dblclick();
  }
  const drawer = page.getByRole('dialog', { name: 'Riadok 3' });
  await expect(drawer).toContainText('FX-7380-0616-A2');
  await expect(drawer.getByRole('radio', { name: /skr\. ISO 7380 M6 x16 A2 TX/ })).toBeChecked();
  await expect(drawer.getByText('Zapamätať kód dodávateľa')).toBeVisible();
  await shot(page, `phase4b-W6h-drawer-${info.project.name}`);
  await drawer.getByTestId('w6h-apply').click();
  await expect(drawer).toHaveCount(0);
  expect(sent).toMatchObject({ article_id: 'a-7380', unit_factor: '1', learn: true, version: 3 });
  await expect(page.getByTestId('w6h-status')).toHaveText('Návrh');
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});

test('4b W6h: Neskladová položka, version conflict message and W6e row opens the card', async ({ page }) => {
  let nonStock = 0;
  await mockApi(page, {
    ...BASE,
    'GET /api/purchasing/documents': {
      body: { items: [{ ...detail([]), lines: 3 }], total: 1 },
    },
    'GET /api/purchasing/documents/d-1': { body: detail([line(1, {}), UNMATCHED]) },
    'POST /api/purchasing/documents/d-1/lines/3/non-stock': () => {
      nonStock += 1;
      return nonStock === 1
        ? { status: 409, body: { detail: { code: 'version_conflict' } } }
        : {
            body: detail(
              [line(1, {}), { ...UNMATCHED, line_status: 'non_stock', match_method: 'non_stock' }],
              'needs_review',
            ),
          };
    },
  });
  await page.goto('/docs/delivery-notes');
  await page.getByTestId('document-row-d-1').click();
  await expect(page).toHaveURL(/\/docs\/delivery-notes\/d-1$/);
  await page.getByTestId('w6h-line-3').click();
  await page.getByRole('button', { name: 'Opraviť' }).click();
  const drawer = page.getByRole('dialog', { name: 'Riadok 3' });
  await drawer.getByTestId('w6h-non-stock').click();
  await expect(drawer.getByRole('alert')).toHaveText('Doklad medzitým zmenil niekto iný – načítajte ho znova.');
  await drawer.getByTestId('w6h-non-stock').click();
  await expect(drawer).toHaveCount(0);
  await expect(page.getByTestId('w6h-line-3')).toContainText('neskladová');
});

test('4b W6h: Money offline banner', async ({ page }) => {
  await mockApi(page, {
    ...BASE,
    'GET /api/purchasing/documents/d-1': { body: { ...detail([UNMATCHED]), money_available: false } },
  });
  await page.goto('/docs/delivery-notes/d-1');
  await expect(page.getByText('Money je nedostupné – položky sa nespárovali.', { exact: false })).toBeVisible();
});
