import type { Locator } from '@playwright/test';

import { expect, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

async function box(l: Locator) {
  const b = await l.boundingBox();
  if (!b) throw new Error('element has no box');
  return b;
}

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
    'GET /api/purchasing/articles': {
      body: Array.from({ length: 14 }, (_, i) => ({
        id: `v-${i}`,
        ...art(`tyč záv. M${i + 2}x2000 4.8 ZN`, `9990001000${String(i + 2).padStart(2, '0')}`, null),
        inactive: false,
      })),
    },
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
    await expect(page.getByTestId('w6h-fees')).toContainText(
      'rozpočítajú rovnomerne podľa počtu položiek ako dodatočné náklady',
    );
    await page.getByRole('button', { name: /Položky/ }).click();
    await page.getByTestId('w6h-line-3').dblclick();
  }
  const drawer = page.getByRole('dialog', { name: 'Riadok 3' });
  await expect(drawer).toContainText('FX-7380-0616-A2');
  await expect(drawer.getByRole('radio', { name: /skr\. ISO 7380 M6 x16 A2 TX/ })).toBeChecked();
  await expect(drawer.getByText('Zapamätať kód dodávateľa')).toBeVisible();
  // pilot 2026-11-20: search above the results, one compact row per article, the list scrolls inside the drawer
  await drawer.getByTestId('w6h-article-search').fill('9990001');
  const list = drawer.getByTestId('w6h-article-list');
  await expect(list).toContainText('tyč záv. M15x2000 4.8 ZN');
  const searchBox = await box(drawer.getByTestId('w6h-article-search'));
  const listBox = await box(list);
  expect(searchBox.y).toBeLessThan(listBox.y);
  const rowBox = await box(list.getByRole('radio', { name: /M4x2000/ }).locator('xpath=..'));
  expect(rowBox.height).toBeLessThanOrEqual(44);
  expect(listBox.height).toBeLessThanOrEqual(420);
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

// #233 — main card with variants (Figma ArticlePickRow 249:3369, drawer 250:90910). Fictional catalogs.
const variant = (size: number) => ({
  article_id: `v-${size}`,
  code: null,
  catalog: `999000100${String(size).padStart(2, '0')}`,
  name: `tyč záv. M${size}×2000 4.8 ZN`,
  unit: 'ks',
  kind: 'variant',
});
const ON_MAIN = line(10, {
  supplier_code: 'FX-976-10-2000',
  name: 'Tyč závitová 4.8 ZN 2m M10',
  line_status: 'needs_review',
  article_id: 'a-main',
  match_method: 'supplier_code',
  warehouse_id: null,
  article: { ...art('Tyč závitová DIN 976 4.8 ZN 2m', '9990001', null), kind: 'main' },
  candidates: [6, 8, 10, 12, 24].map(variant),
});

test('#233 W6h: main card is never selectable, its variants are italic and pickable (DL-B11) @mobile', async ({
  page,
}, info) => {
  const mobile = info.project.name !== 'desktop';
  let sent: Record<string, unknown> | null = null;
  const withVariant = line(2, { article: { ...art('tyč záv. M8×2000 4.8 ZN', '99900010008', null), kind: 'variant' } });
  const before = {
    ...detail([line(1, {}), withVariant, ON_MAIN]),
    checks: [{ id: 'DL-B11', level: 'blocking', params: { n: 10 } }],
  };
  await mockApi(page, {
    ...BASE,
    'GET /api/purchasing/documents/d-1': { body: before },
    'POST /api/purchasing/documents/d-1/lines/10/article': (body) => {
      sent = body as Record<string, unknown>;
      return {
        body: detail(
          [
            line(1, {}),
            withVariant,
            {
              ...ON_MAIN,
              line_status: 'matched',
              match_method: 'user',
              candidates: [],
              article: { ...art('tyč záv. M10×2000 4.8 ZN', '99900010010', null), kind: 'variant' },
            },
          ],
          'needs_review',
          4,
        ),
      };
    },
  });
  await page.goto('/docs/delivery-notes/d-1');
  if (mobile) {
    await expect(page.getByTestId('m13b-line-2').locator('.italic')).toHaveText('tyč záv. M8×2000 4.8 ZN');
    await expect(page.getByTestId('m13b-summary')).toContainText('1 nespárovaných');
    await page.getByTestId('m13b-line-10').click();
  } else {
    await expect(page.getByTestId('w6h-line-2').locator('td.italic')).toHaveText('tyč záv. M8×2000 4.8 ZN');
    await page.getByTestId('w6h-checks-toggle').click();
    await expect(page.getByTestId('check-DL-B11')).toContainText(
      'Riadok 10 je na hlavnej karte, ktorá má varianty – vyberte variant.',
    );
    await page.getByTestId('w6h-checks-toggle').click();
    await page.getByTestId('w6h-line-10').dblclick();
  }
  const drawer = page.getByRole('dialog', { name: 'Riadok 10' });
  const main = drawer.getByTestId('w6h-pick-main');
  await expect(main).toContainText('hlavná karta');
  await expect(main.getByRole('radio')).toBeDisabled();
  await expect(drawer.getByTestId('w6h-main-card-hint')).toHaveText(
    'Na hlavnú kartu s variantmi sa tovar neprijíma – vyberte variant.',
  );
  const variants = drawer.getByTestId('w6h-pick-variant');
  await expect(variants).toHaveCount(5);
  await expect(variants.first().locator('.italic')).toHaveText('tyč záv. M6×2000 4.8 ZN');
  const mainBox = await box(main.locator('.type-small'));
  const variantBox = await box(variants.first().locator('.italic'));
  expect(variantBox.x).toBeGreaterThan(mainBox.x); // indented under its main card
  await drawer.getByRole('radio', { name: /M10×2000/ }).check();
  await shot(page, `issue233-W6h-variants-${info.project.name}`);
  await drawer.getByTestId('w6h-apply').click();
  await expect(drawer).toHaveCount(0);
  expect(sent).toMatchObject({ article_id: 'v-10' });
});

// W6h Katalóg (Erik 24 Nov 2026, Figma 264:91756 / 265:99286): bigger search, stock per warehouse, pick → drawer
const stock = (wh: string, code: string, name: string, qty: string) => ({
  warehouse_id: wh,
  code,
  name,
  qty,
  reserved: '0',
  ordered: '0',
  expected: qty,
  available: qty,
  unit_price: '1.642',
});
const catRow = (id: string, kind: string, catalog: string, name: string, extra: Record<string, unknown> = {}) => ({
  id,
  code: null,
  catalog,
  name,
  ean: null,
  unit: 'ks',
  inactive: false,
  kind,
  parent_id: kind === 'variant' ? 'a-main' : null,
  plu: kind === 'article' ? null : 'var_a0310',
  last_price: kind === 'main' ? null : '1.65',
  eshop: kind !== 'article',
  stocks: kind === 'main' ? [] : [stock('w-20', '20', 'Senica', '18'), stock('w-99', '99', 'Externý sklad', '6')],
  ...extra,
});
const ROWS = [
  catRow('a-main', 'main', '9990001', 'Tyč závitová DIN 976 4.8 ZN 2m'),
  catRow('v-8', 'variant', '999000100008', 'tyč záv. M8×2000 4.8 ZN'),
  catRow('v-10', 'variant', '999000100010', 'tyč záv. M10×2000 4.8 ZN'),
  catRow('a-a4', 'article', '309009100010', 'tyc zav. M10 A4-70'),
];
const CATALOG = { total: ROWS.length, items: ROWS, stock_available: true, cached: true };

test('W6h Katalóg: search, stock per warehouse, columns, pick a variant into the line @mobile', async ({
  page,
}, info) => {
  const mobile = info.project.name !== 'desktop';
  let sent: Record<string, unknown> | null = null;
  const queries: string[] = [];
  await mockApi(page, {
    ...BASE,
    'GET /api/purchasing/documents/d-1': { body: { ...detail([line(1, {}), ON_MAIN]), can_create_article: true } },
    'GET /api/purchasing/catalog': () => ({ body: CATALOG }),
    'POST /api/purchasing/documents/d-1/lines/10/article': (body) => {
      sent = body as Record<string, unknown>;
      return { body: detail([line(1, {}), { ...ON_MAIN, line_status: 'matched', candidates: [] }], 'needs_review', 4) };
    },
  });
  page.on('request', (r) => {
    if (r.url().includes('/api/purchasing/catalog')) queries.push(new URL(r.url()).searchParams.get('q') ?? '');
  });
  await page.goto('/docs/delivery-notes/d-1');
  if (mobile) await page.getByTestId('m13b-line-10').click();
  else await page.getByTestId('w6h-line-10').dblclick();
  await page.getByTestId('w6h-open-catalog').click();
  const win = page.getByTestId('w6h-catalog');
  await expect(win).toBeVisible();
  await win.getByTestId('w6h-catalog-search').fill('%tyč%M10%');
  await expect.poll(() => queries.at(-1)).toBe('%tyč%M10%');
  await expect(win.getByTestId('w6h-catalog-status')).toHaveText('4 položky');
  await expect(win.getByTestId('w6h-catalog-pick')).toBeDisabled();
  await win.getByTestId('w6h-catalog-row-main').click();
  await expect(win.getByTestId('w6h-catalog-pick')).toBeDisabled(); // DL-B11: never the main card
  await expect(win.getByTestId('w6h-catalog-new-variant')).toHaveText(
    'Založiť variant k „Tyč závitová DIN 976 4.8 ZN 2m“',
  );
  await win.getByTestId('w6h-catalog-row-variant').nth(1).click();
  await expect(win.getByTestId('w6h-catalog-stock')).toContainText('Zásoby · tyč záv. M10×2000 4.8 ZN');
  if (!mobile) {
    await expect(win.getByTestId('w6h-catalog-stock')).toContainText('99 – Externý sklad');
    await expect(win.getByRole('columnheader', { name: 'Zásoba 20 – Senica' })).toBeVisible();
    await expect(win.getByTestId('w6h-catalog-row-variant').nth(1)).toContainText('18,0000');
    await shot(page, 'w6h-catalog-desktop');
    // the column chooser like in Money: add „Čiarový kód (EAN)“
    await win.getByTestId('w6h-catalog-columns').click();
    const chooser = page.getByTestId('w6h-catalog-chooser');
    await chooser.getByTestId('w6h-chooser-hidden').getByText('Čiarový kód (EAN)').dblclick();
    await chooser.getByTestId('w6h-chooser-ok').click();
    await expect(win.getByRole('columnheader', { name: 'Čiarový kód' })).toBeVisible();
  } else {
    await expect(win.getByTestId('w6h-catalog-stock')).toContainText('20 – Senica: 18');
    await shot(page, 'w6h-catalog-mobile');
  }
  await win.getByTestId('w6h-catalog-pick').click();
  await expect(win).toHaveCount(0);
  const drawer = page.getByTestId('w6h-drawer');
  await expect(drawer.getByTestId('w6h-article-list')).toContainText('tyč záv. M10×2000 4.8 ZN');
  await drawer.getByTestId('w6h-apply').click();
  await expect.poll(() => sent?.article_id).toBe('v-10');
});

test('W6h Katalóg: „Založiť variant k …“ opens the new-article form with that main card', async ({ page }) => {
  await mockApi(page, {
    ...BASE,
    'GET /api/purchasing/documents/d-1': { body: { ...detail([line(1, {}), ON_MAIN]), can_create_article: true } },
    'GET /api/purchasing/catalog': { body: CATALOG },
  });
  await page.goto('/docs/delivery-notes/d-1');
  await page.getByTestId('w6h-line-10').dblclick();
  await page.getByTestId('w6h-open-catalog').click();
  const win = page.getByTestId('w6h-catalog');
  await win.getByTestId('w6h-catalog-search').fill('9990001');
  await win.getByTestId('w6h-catalog-row-main').click();
  await win.getByTestId('w6h-catalog-new-variant').click();
  await expect(win).toHaveCount(0);
  const drawer = page.getByTestId('w6h-drawer');
  await expect(drawer).toContainText('Tyč závitová DIN 976 4.8 ZN 2m');
  await expect(drawer.getByRole('heading')).toHaveText('Riadok 10 · nový artikel v Money');
});

test('W6h Katalóg: the whole catalog from the cache — paging, sorting, Money offline', async ({ page }) => {
  const asked: URLSearchParams[] = [];
  await mockApi(page, {
    ...BASE,
    'GET /api/purchasing/documents/d-1': { body: { ...detail([line(1, {}), ON_MAIN]), can_create_article: true } },
  });
  // 150 cached articles: 100 on the first page, the rest when the end of the list comes into view
  const all = Array.from({ length: 150 }, (_, i) =>
    catRow(`a-${i}`, 'article', `3110${String(i).padStart(4, '0')}`, `Artikel ${i}`),
  );
  await page.route('**/api/purchasing/catalog?**', async (route) => {
    const p = new URL(route.request().url()).searchParams;
    asked.push(p);
    const offset = Number(p.get('offset'));
    const items = all.slice(offset, offset + Number(p.get('limit')));
    await route.fulfill({ json: { total: all.length, items, stock_available: offset === 0, cached: true } });
  });
  await page.goto('/docs/delivery-notes/d-1');
  await page.getByTestId('w6h-line-10').dblclick();
  await page.getByTestId('w6h-open-catalog').click();
  const win = page.getByTestId('w6h-catalog');
  await win.getByTestId('w6h-catalog-search').fill('');
  await expect(win.getByTestId('w6h-catalog-status')).toHaveText('Celý katalóg · 150 položiek');
  await expect(win.getByTestId('w6h-catalog-row-article')).toHaveCount(100);
  await win.getByTestId('w6h-catalog-more').scrollIntoViewIfNeeded();
  await expect(win.getByTestId('w6h-catalog-row-article')).toHaveCount(150);
  await expect(win.getByTestId('w6h-catalog-more')).toHaveCount(0);
  // the drawer opens the window with the line text; the empty search then pages through the whole catalog
  expect(asked.filter((p) => p.get('q') === '').map((p) => p.get('offset'))).toEqual(['0', '100']);
  await expect(win.getByTestId('w6h-catalog-status')).toContainText('Money je nedostupné'); // page 2 had no stock
  await win.getByTestId('w6h-catalog-sort-name').click();
  await expect.poll(() => asked.at(-1)?.get('sort')).toBe('name');
  expect(asked.at(-1)?.get('desc')).toBe('false');
  await win.getByTestId('w6h-catalog-sort-name').click();
  await expect.poll(() => asked.at(-1)?.get('desc')).toBe('true');
  await expect(win.getByRole('columnheader', { name: 'Názov' })).toHaveAttribute('aria-sort', 'descending');
});
