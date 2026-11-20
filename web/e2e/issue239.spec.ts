import type { Page, Route } from '@playwright/test';

import { expect, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

// #239 / D32 — „Založiť artikel v Money“ in the W6h line drawer (Figma variant 255:91329, catalog taken 255:92189,
// new main + variant 256:90924; M13b = the same form in the bottom sheet). Every catalog and name is fictional.

const WAREHOUSE = { ...ME, person: { ...ME.person, role: 'warehouse' } };
const LINE = {
  line_no: 10,
  supplier_code: 'FX-976-10-2000',
  ean: null,
  name: 'Tyč závitová 4.8 ZN 2m M10',
  qty: '0.1000',
  unit: 'sks',
  unit_price: '180.2900',
  vat_rate: '23',
  line_total: '18.03',
  is_fee: false,
  line_status: 'unmatched',
  article_id: null,
  match_method: 'none',
  unit_factor: null,
  warehouse_id: null,
  warehouse_code: null,
  candidates: [],
  article: null,
  qty_our: null,
  price_our: null,
  new_article: null,
};
const detail = (line: Record<string, unknown>, version = 3, extra: Record<string, unknown> = {}) => ({
  id: 'd-1',
  source: 'mail',
  kind: 'invoice',
  status: 'missing_data',
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
  total: '18.03',
  lines: 1,
  blocking: 1,
  warnings: 0,
  error: null,
  created_at: '2026-10-31T08:00:00Z',
  delivery_note_number: null,
  order_reference: null,
  vat_recap: [{ rate: '23', base: '18.03', vat: '0.00' }],
  fees: [],
  extract_method: 'pdf_llm',
  field_confidence: {},
  checks: [{ id: 'DL-B4', level: 'blocking', params: { n: 1, lines: [10] } }],
  message_id: null,
  version,
  money_available: true,
  can_create_article: true,
  supplier: { name: 'Fiktívny dodávateľ s.r.o.', ico: '27654321', dic: null, icdph: null },
  series: 'DLP SE',
  template: {},
  warehouses: [{ id: 'w-20', code: '20', name: 'Senica' }],
  items: [LINE],
  ...extra,
  ...(line ? { items: [line] } : {}),
});
const MAIN = {
  id: 'm-1',
  code: null,
  catalog: '9990001',
  name: 'Tyč závitová DIN 976 4.8 ZN 2m',
  ean: null,
  unit: 'ks',
};
const BASE = {
  'GET /api/auth/me': { body: WAREHOUSE },
  'GET /api/auth/persons': { body: { ...ME_PICKER, persons: [WAREHOUSE.person] } },
  'GET /api/system/info': { body: { admin_contact_email: null, features: { money: true } } },
  'GET /api/purchasing/articles': { body: [{ ...MAIN, kind: 'article', inactive: false }] },
};
const created = (id: string, katalog: string, nazev: string, parent: string | null = null) => ({
  id,
  katalog,
  nazev,
  parent_id: parent,
  unit: 'ks',
});

/** Catalogs already in Money for the live check (`?katalog=` is not part of the mockApi key). */
async function money(page: Page, taken: string[]) {
  await page.route('**/api/purchasing/articles/catalog-free**', (route: Route) => {
    const k = new URL(route.request().url()).searchParams.get('katalog') ?? '';
    const hit = taken.includes(k);
    return route.fulfill({ json: { free: !hit, article: hit ? { katalog: k, nazev: 'Iný artikel' } : null } });
  });
  await page.route('**/api/purchasing/catalog-proposal**', (route: Route) => {
    const u = new URL(route.request().url()).searchParams;
    const base = u.get('parent_id') === 'm-1' ? '9990001' : (u.get('main_catalog') ?? '');
    return route.fulfill({ json: { katalog: `${base}00010`, size: 10, main_catalog: base } });
  });
}

async function openNew(page: Page, mobile: boolean) {
  await page.goto('/docs/delivery-notes/d-1');
  await expect(page.getByTestId('screen-w6h')).toBeVisible();
  if (mobile) await page.getByTestId('m13b-line-10').click();
  else await page.getByTestId('w6h-line-10').dblclick();
  const drawer = page.getByRole('dialog', { name: /Riadok 10/ });
  await drawer.getByTestId('w6h-new-article-link').click();
  await expect(drawer.getByRole('heading')).toHaveText('Riadok 10 · nový artikel v Money');
  await expect(drawer).toContainText(
    'Jednotku ks, DPH a druh artikla doplní Money. Karta bude v nezaradenej skupine, bez kategórie a parametrov',
  );
  return drawer;
}

test('#239 W6h: variant of an existing main card, proposal M10 → 00010, card picked @mobile', async ({
  page,
}, info) => {
  const mobile = info.project.name !== 'desktop';
  let sent: Record<string, unknown> | null = null;
  const card = created('v-new', '999000100010', 'Tyč závitová 4.8 ZN 2m M10', 'm-1');
  await mockApi(page, {
    ...BASE,
    'GET /api/purchasing/documents/d-1': { body: detail(LINE) },
    'POST /api/purchasing/documents/d-1/lines/10/new-article': (body) => {
      sent = body as Record<string, unknown>;
      const line = {
        ...LINE,
        line_status: 'matched',
        article_id: 'v-new',
        match_method: 'user',
        article: { code: null, catalog: card.katalog, name: card.nazev, ean: null, unit: 'ks', kind: 'variant' },
      };
      return {
        body: {
          status: 'done',
          main: null,
          variant: card,
          error: null,
          article_id: 'v-new',
          document: detail(line, 4),
        },
      };
    },
  });
  await money(page, ['9990001']);
  const drawer = await openNew(page, mobile);
  await drawer.getByTestId('w6h-new-variant').click();
  await drawer.getByTestId('w6h-new-parent').click();
  await drawer.getByTestId('w6h-new-parent-search').fill('9990001');
  await drawer.getByTestId('w6h-new-parent-option').click();
  await expect(drawer.getByTestId('w6h-new-name')).toHaveValue('Tyč závitová 4.8 ZN 2m M10');
  await expect(drawer.getByTestId('w6h-new-catalog')).toHaveValue('999000100010');
  await expect(drawer.getByTestId('w6h-new-catalog-note')).toHaveText(
    'Návrh: katalóg hlavnej karty + rozmer M10 (00010). V Money je voľný.',
  );
  await expect(drawer.getByTestId('w6h-new-submit')).toHaveText('Založiť v Money');
  await expect(drawer.getByTestId('w6h-new-submit')).toBeEnabled();
  await shot(page, `issue239-W6h-variant-${info.project.name}`);
  await drawer.getByTestId('w6h-new-submit').click();
  await expect(page.getByText('Artikel 999000100010 bol založený v Money.')).toBeVisible();
  await expect(drawer.getByTestId('w6h-article-list')).toContainText('999000100010'); // back in the picker
  await expect(drawer.getByRole('radio', { name: /Tyč závitová 4.8 ZN 2m M10/ })).toBeChecked();
  expect(sent).toEqual({
    mode: 'variant',
    parent_id: 'm-1',
    variant: { katalog: '999000100010', nazev: 'Tyč závitová 4.8 ZN 2m M10' },
    version: 3,
  });
});

test('#239 W6h: a catalog already in Money blocks the button @mobile', async ({ page }, info) => {
  const mobile = info.project.name !== 'desktop';
  await mockApi(page, { ...BASE, 'GET /api/purchasing/documents/d-1': { body: detail(LINE) } });
  await money(page, ['9990001']);
  const drawer = await openNew(page, mobile);
  await expect(drawer.getByTestId('w6h-new-name')).toHaveValue('Tyč závitová 4.8 ZN 2m M10');
  await drawer.getByTestId('w6h-new-name').fill('Tyč závitová DIN 976 4.8 ZN 2m');
  await drawer.getByTestId('w6h-new-catalog').fill('9990001');
  await expect(drawer.getByTestId('w6h-new-catalog-note')).toHaveText(
    'Tento katalóg už v Money existuje – zadajte iný.',
  );
  await expect(drawer.getByTestId('w6h-new-catalog')).toHaveAttribute('aria-invalid', 'true');
  await expect(drawer.getByTestId('w6h-new-submit')).toBeDisabled();
  await shot(page, `issue239-W6h-catalog-taken-${info.project.name}`);
  await drawer.getByTestId('w6h-new-catalog').fill('9990002');
  await expect(drawer.getByTestId('w6h-new-catalog-note')).toHaveText('V Money je voľný.');
  await expect(drawer.getByTestId('w6h-new-submit')).toBeEnabled();
});

test('#239 W6h: new main card + variant, then a partial result and „Založiť variant“ @mobile', async ({
  page,
}, info) => {
  const mobile = info.project.name !== 'desktop';
  const bodies: Record<string, unknown>[] = [];
  const main = created('m-new', '9990002', 'Tyč závitová DIN 976 4.8 ZN 2m');
  const partialLine = { ...LINE, new_article: { status: 'partial', main, error: 'money_error' } };
  await mockApi(page, {
    ...BASE,
    'GET /api/purchasing/documents/d-1': { body: detail(LINE) },
    'POST /api/purchasing/documents/d-1/lines/10/new-article': (body) => {
      bodies.push(body as Record<string, unknown>);
      if (bodies.length === 1)
        return {
          body: {
            status: 'partial',
            main,
            variant: null,
            error: 'money_error',
            article_id: null,
            document: detail(partialLine, 4),
          },
        };
      const v = created('v-new', '999000200010', 'Tyč závitová 4.8 ZN 2m M10', 'm-new');
      const done = { ...LINE, line_status: 'matched', article_id: 'v-new', match_method: 'user' };
      return {
        body: { status: 'done', main, variant: v, error: null, article_id: 'v-new', document: detail(done, 5) },
      };
    },
  });
  await money(page, ['9990001']);
  const drawer = await openNew(page, mobile);
  await drawer.getByTestId('w6h-new-variant').click();
  await drawer.getByTestId('w6h-new-parent').click();
  await drawer.getByTestId('w6h-new-parent-new').click();
  await expect(drawer.getByTestId('w6h-new-parent')).toContainText('+ Nová hlavná karta');
  await expect(drawer.getByTestId('w6h-new-main-name')).toHaveValue('Tyč závitová 4.8 ZN 2m');
  await drawer.getByTestId('w6h-new-main-name').fill('Tyč závitová DIN 976 4.8 ZN 2m');
  await drawer.getByTestId('w6h-new-main-catalog').fill('9990002');
  await expect(drawer.getByTestId('w6h-new-main-catalog-note')).toHaveText('V Money je voľný.');
  await expect(drawer.getByTestId('w6h-new-catalog')).toHaveValue('999000200010'); // recomputed from the main
  await expect(drawer.getByTestId('w6h-new-catalog-note')).toHaveText(
    'Návrh: katalóg novej hlavnej karty + rozmer M10 (00010).',
  );
  await expect(drawer.getByTestId('w6h-new-submit')).toHaveText('Založiť obe karty v Money');
  await shot(page, `issue239-W6h-new-main-variant-${info.project.name}`);
  await drawer.getByTestId('w6h-new-submit').click();
  await expect(drawer).toContainText('Hlavná karta 9990002 je založená, variant nie: Money zápis odmietlo.');
  await expect(drawer.getByTestId('w6h-new-main-catalog')).toBeDisabled();
  await expect(drawer.getByTestId('w6h-new-submit')).toHaveText('Založiť variant');
  await shot(page, `issue239-W6h-partial-${info.project.name}`);
  await drawer.getByTestId('w6h-new-submit').click();
  await expect(page.getByText('Artikel 999000200010 bol založený v Money.')).toBeVisible();
  expect(bodies[0]).toEqual({
    mode: 'main_and_variant',
    main: { katalog: '9990002', nazev: 'Tyč závitová DIN 976 4.8 ZN 2m' },
    variant: { katalog: '999000200010', nazev: 'Tyč závitová 4.8 ZN 2m M10' },
    version: 3,
  });
  expect(bodies[1]).toMatchObject({ mode: 'main_and_variant', version: 4 });
});

test('#239 W6h: no link without the permission or when Money is offline', async ({ page }) => {
  await mockApi(page, {
    ...BASE,
    'GET /api/purchasing/documents/d-1': { body: detail(LINE, 3, { can_create_article: false }) },
  });
  await page.goto('/docs/delivery-notes/d-1');
  await page.getByTestId('w6h-line-10').dblclick();
  const drawer = page.getByRole('dialog', { name: /Riadok 10/ });
  await expect(drawer.getByTestId('w6h-article-search')).toBeVisible();
  await expect(drawer.getByTestId('w6h-new-article-link')).toHaveCount(0);
});
