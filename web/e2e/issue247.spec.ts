import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import type { Page } from '@playwright/test';

import { expect, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

// #247 / D33 — the received delivery note is written to Money only as a KONCEPT. Figma: confirm `44:38842`,
// koncept v Money `44:41789`, error `44:42554`, unknown `44:43319`, duplicate `44:44083`, template missing `44:44847`,
// Settings 11e `72:62825`. Every company, number and price is fictional.

const WAREHOUSE = { ...ME, person: { ...ME.person, role: 'warehouse' } };
const art = (name: string, catalog: string) => ({ code: null, catalog, name, ean: null, unit: 'ks', kind: 'article' });
const line = (n: number, name: string, catalog: string, qty: string, price: string, total: string) => ({
  line_no: n,
  supplier_code: `FX-${n}`,
  ean: null,
  name: `Text dodávateľa ${n}`,
  qty,
  unit: 'ks',
  unit_price: price,
  vat_rate: '23',
  line_total: total,
  is_fee: false,
  line_status: 'matched',
  article_id: `a-${n}`,
  match_method: 'supplier_code',
  unit_factor: '1.000000',
  warehouse_id: 'w-20',
  warehouse_code: '20',
  candidates: [],
  article: art(name, catalog),
  qty_our: qty,
  price_our: price,
  new_article: null,
});
const LINES = [
  line(1, 'skr. M10 x30 A2 DIN 933', '309903010030', '5000', '0.0612', '306.00'),
  line(2, 'mat. M10 A2 ISO 4032', '311403210000', '2000', '0.0205', '41.00'),
];
const FEE = { ...line(3, 'x', 'x', '1', '12.00', '12.00'), is_fee: true, name: 'Doprava', article: null };
const detail = (over: Record<string, unknown> = {}) => ({
  id: 'd-1',
  source: 'mail',
  kind: 'invoice',
  status: 'needs_review',
  filename: 'FA-2611452.pdf',
  branch_id: 'b-se',
  branch_name: 'Senica',
  centre_code: '20',
  warehouse_code: '20',
  supplier_name: 'Fiktívny dodávateľ s.r.o.',
  supplier_ico: '27654321',
  supplier_money_id: 's-1',
  doc_number: '2611452',
  doc_date: '2026-11-20',
  currency: 'EUR',
  total: '347.00',
  lines: 2,
  blocking: 0,
  warnings: 1,
  error: null,
  created_at: '2026-11-23T08:00:00Z',
  money_number: null,
  delivery_note_number: 'DL-2026-04417',
  order_reference: null,
  vat_recap: [{ rate: '23', base: '347.00', vat: '79.81' }],
  fees: [{ name: 'Doprava', amount: '12.00' }],
  extract_method: 'pdf_llm',
  field_confidence: {},
  checks: [{ id: 'DL-W5', level: 'warning', params: { sum: '12.00' } }],
  message_id: null,
  version: 3,
  money_available: true,
  can_create_article: false,
  can_write: true,
  write: null,
  supplier: { name: 'Fiktívny dodávateľ s.r.o.', ico: '27654321', dic: null, icdph: null },
  series: 'DLP SE',
  template: {},
  warehouses: [{ id: 'w-20', code: '20', name: 'Senica' }],
  items: [...LINES, FEE],
  ...over,
});
const WRITE = {
  state: 'created',
  number: 'DLP0412/2026',
  money_id: 'm-1',
  mismatches: [] as unknown[],
  reconciled: false,
  error: null,
  written_at: '2026-11-23T09:14:00Z',
};
const created = (over: Record<string, unknown> = {}) =>
  detail({ status: 'created', money_number: 'DLP0412/2026', version: 4, write: WRITE, ...over });
const BASE = {
  'GET /api/auth/me': { body: WAREHOUSE },
  'GET /api/auth/persons': { body: { ...ME_PICKER, persons: [WAREHOUSE.person] } },
  'GET /api/system/info': { body: { admin_contact_email: null, features: { money: true } } },
};

async function open(page: Page, mobile: boolean) {
  await page.goto('/docs/delivery-notes/d-1');
  await expect(page.getByTestId('screen-w6h')).toBeVisible();
  return page.getByTestId(mobile ? 'm13b-create' : 'w6h-create');
}

test('#247 W6h: confirm dialog → „Koncept v Money“ with the read-back check @mobile', async ({ page }, info) => {
  const mobile = info.project.name !== 'desktop';
  let sent: unknown = null;
  await mockApi(page, {
    ...BASE,
    'GET /api/purchasing/documents/d-1': { body: detail() },
    'POST /api/purchasing/documents/d-1/create': (body) => {
      sent = body;
      return { body: created() };
    },
  });
  const create = await open(page, mobile);
  await expect(create).toBeEnabled();
  await create.click();
  const dialog = page.getByRole('dialog', { name: 'Zapísať dodací list do Money ako koncept?' });
  await expect(dialog).toContainText('Fiktívny dodávateľ s.r.o. (IČO 27654321)');
  await expect(dialog).toContainText('DL-2026-04417 · párovací symbol 2611452');
  await expect(dialog).toContainText('2 (všetky spárované)');
  await expect(dialog).toContainText('20 – Senica · DLP SE');
  await expect(dialog).toContainText('347,00 € bez DPH');
  await expect(dialog).toContainText('pri zápise (teraz, Europe/Bratislava)');
  await expect(dialog).toContainText(
    'Zapíše sa ako koncept s popisom „Smartmail · …“ – sklad sa nepohne, kým ho v Money nedokončíte. Poplatky 12,00 € sa rozpočítajú rovnomerne do položiek ako dodatočné náklady.',
  );
  await shot(page, `issue247-W6h-confirm-${info.project.name}`);
  await dialog.getByTestId('w6h-write-confirm').click();
  await expect(page.getByTestId('w6h-status')).toHaveText('Koncept v Money č. DLP0412/2026');
  await expect(page.getByTestId('w6h-write-banner')).toContainText(
    'Doklad je v Money uložený ako koncept – skontrolujte ho a dokončite v Money (zrušte „Uložiť ako koncept“). Kontrola po zápise: 2/2 položiek',
  );
  await expect(page.getByText('Koncept DLP0412/2026 je v Money.')).toBeVisible();
  await expect(page.getByTestId(mobile ? 'm13b-create' : 'w6h-create')).toHaveCount(0); // no „Vrátiť“, no 2nd write
  expect(sent).toEqual({ version: 3 });
  await shot(page, `issue247-W6h-koncept-${info.project.name}`);
});

test('#247 W6h: read-back mismatch shows the red banner (never edits or deletes the koncept)', async ({ page }) => {
  const mismatch = created({
    write: {
      ...WRITE,
      mismatches: [{ field: 'qty', line: 2, expected: '2000', got: '2001' }],
    },
  });
  await mockApi(page, { ...BASE, 'GET /api/purchasing/documents/d-1': { body: mismatch } });
  await page.goto('/docs/delivery-notes/d-1');
  const banner = page.getByTestId('w6h-write-banner');
  await expect(banner).toContainText('Skontrolujte koncept v Money č. DLP0412/2026 – po zápise nesedí:');
  await expect(banner).toContainText('Riadok 2: množstvo 2000, v Money 2001.');
});

test('#247 W6h: duplicate in Money (DL-B3) @mobile', async ({ page }, info) => {
  const mobile = info.project.name !== 'desktop';
  let posted = false;
  const dup = detail({
    status: 'missing_data',
    blocking: 1,
    checks: [{ id: 'DL-B3', level: 'blocking', params: { number: 'DLP0398/2026', money: true } }],
  });
  await mockApi(page, {
    ...BASE,
    'GET /api/purchasing/documents/d-1': () => ({ body: posted ? dup : detail() }),
    'POST /api/purchasing/documents/d-1/create': () => {
      posted = true;
      return { status: 409, body: { detail: { code: 'duplicate', number: 'DLP0398/2026' } } };
    },
  });
  await (await open(page, mobile)).click();
  await page.getByTestId('w6h-write-confirm').click();
  await expect(page.getByTestId('w6h-write-banner')).toHaveText(
    'DL-B3 · Tento dodací list už v Money je: DLP0398/2026.',
  );
  await expect(page.getByTestId('w6h-status')).toHaveText('Duplicita');
  await expect(page.getByTestId(mobile ? 'm13b-create' : 'w6h-create')).toBeDisabled();
  await shot(page, `issue247-W6h-duplicate-${info.project.name}`);
});

test('#247 W6h: branch without a template (DL-B6) @mobile', async ({ page }, info) => {
  const mobile = info.project.name !== 'desktop';
  await mockApi(page, {
    ...BASE,
    'GET /api/purchasing/documents/d-1': {
      body: detail({
        status: 'missing_data',
        blocking: 1,
        checks: [{ id: 'DL-B6', level: 'blocking', params: { missing: ['template'], koncept: true } }],
      }),
    },
  });
  const create = await open(page, mobile);
  await expect(create).toBeDisabled();
  const banner = page.getByTestId('w6h-write-banner');
  await expect(banner).toContainText(
    'DL-B6 · Pobočka Senica nemá vzorový dodací list – vyberte ho v Nastaveniach › Pobočky a osoby › Money.',
  );
  await shot(page, `issue247-W6h-template-missing-${info.project.name}`);
  await banner.getByRole('button', { name: 'Otvoriť Nastavenia › Pobočky' }).click();
  await expect(page).toHaveURL(/\/settings\/branches/);
});

test('#247 W6h: incomplete template names the branch and the missing values (pilot 2026-11-23)', async ({ page }) => {
  await mockApi(page, {
    ...BASE,
    'GET /api/purchasing/documents/d-1': {
      body: detail({
        status: 'missing_data',
        blocking: 1,
        checks: [{ id: 'DL-B6', level: 'blocking', params: { missing: ['Group_ID', 'TypObsahu'], koncept: true } }],
      }),
    },
  });
  await open(page, false);
  await expect(page.getByTestId('w6h-write-banner')).toContainText(
    'Vzorový dodací list pobočky Senica je neúplný – chýba: skupina zoznamu (DLP …), položka s artiklom a skladom.',
  );
});

test('#247 W6h: document without a branch → „Vyberte pobočku“ ▾ assigns one (pilot 2026-11-23) @mobile', async ({
  page,
}, info) => {
  const sent: unknown[] = [];
  await mockApi(page, {
    ...BASE,
    'GET /api/purchasing/documents/d-1': {
      body: detail({
        branch_id: null,
        branch_name: null,
        centre_code: null,
        warehouse_code: null,
        status: 'missing_data',
        blocking: 1,
        branch_options: [
          { id: 'b-nr', name: 'Nitra' },
          { id: 'b-se', name: 'Senica' },
        ],
        checks: [{ id: 'DL-B1', level: 'blocking', params: { missing: ['branch'], koncept: true } }],
      }),
    },
    'PUT /api/purchasing/documents/d-1/branch': (body) => {
      sent.push(body);
      return {
        body: detail({
          branch_id: 'b-nr',
          branch_name: 'Nitra',
          centre_code: '30',
          warehouse_code: '30',
          version: 4,
          branch_options: [
            { id: 'b-nr', name: 'Nitra' },
            { id: 'b-se', name: 'Senica' },
          ],
        }),
      };
    },
  });
  await open(page, info.project.name !== 'desktop');
  await expect(page.getByTestId('w6h-write-banner')).toContainText('DL-B1 · Dodací list nemá priradenú pobočku');
  const chip = page.getByTestId('w6h-branch-chip');
  await expect(chip).toHaveText('Vyberte pobočku');
  await chip.click();
  await page
    .getByRole('menuitemradio', { name: 'Nitra' })
    .or(page.getByRole('menuitem', { name: 'Nitra' }))
    .click();
  await expect.poll(() => sent).toEqual([{ branch_id: 'b-nr', version: 3 }]);
  await expect(chip).toHaveText('Pobočka Nitra · stredisko 30 · sklad 30');
  await expect(page.getByTestId('w6h-write-banner')).toHaveCount(0);
});

test('#247 W6h: Money did not answer → „Overiť teraz“ reconciles by SMID', async ({ page }) => {
  let calls = 0;
  const unknown = detail({
    status: 'unknown',
    version: 4,
    write: {
      state: 'unknown',
      number: null,
      money_id: null,
      mismatches: [],
      reconciled: false,
      error: 'x',
      written_at: null,
    },
  });
  await mockApi(page, {
    ...BASE,
    'GET /api/purchasing/documents/d-1': () => ({ body: calls ? unknown : detail() }),
    'POST /api/purchasing/documents/d-1/create': (body) => {
      calls += 1;
      if (calls === 1) return { status: 503, body: { detail: { code: 'money_unavailable' } } };
      expect(body).toEqual({ version: 4 });
      return { body: created({ write: { ...WRITE, reconciled: true } }) };
    },
  });
  await (await open(page, false)).click();
  await page.getByTestId('w6h-write-confirm').click();
  const banner = page.getByTestId('w6h-write-banner');
  await expect(banner).toContainText('Money neodpovedalo včas. Overujem podľa SMID');
  await expect(page.getByTestId('w6h-status')).toHaveText('Neistý stav');
  await expect(page.getByTestId('w6h-create')).toBeDisabled();
  await shot(page, 'issue247-W6h-unknown-desktop');
  await banner.getByRole('button', { name: 'Overiť teraz' }).click();
  await expect(page.getByTestId('w6h-status')).toHaveText('Koncept v Money č. DLP0412/2026');
  expect(calls).toBe(2);
});

test('#247 W6h: without the Settings 14 switch the button stays disabled', async ({ page }) => {
  await mockApi(page, { ...BASE, 'GET /api/purchasing/documents/d-1': { body: detail({ can_write: false }) } });
  const create = await open(page, false);
  await expect(create).toBeDisabled();
  await expect(create).toHaveAttribute('title', /vypnutý v Nastaveniach › Nákup a sklad/);
});

// ----- Settings 11e -----

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
  id: 'b-se',
  name: 'Pobočka Senica',
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
const CENTRE = '20202020-2020-4020-8020-202020202020';
const WH = '21212121-2121-4121-8121-212121212121';
const TPL = (id: string, number: string) => ({
  id,
  number,
  supplier: 'Fiktívny dodávateľ s.r.o.',
  issued_on: '2026-11-18',
  cached_at: '2026-11-23T08:00:00Z',
  missing: [],
  centre: '20 – Senica',
  series: 'DLP SE – Dodacie listy prijaté Senica',
});

test('#247 Settings 11e: branch warehouse, template note „Vybrať iný“ and „Overiť“', async ({ page }) => {
  const saved: unknown[] = [];
  let picked: unknown = null;
  await mockApi(page, {
    'GET /api/auth/me': { body: ADMIN },
    'GET /api/auth/persons': { body: { ...ME_PICKER, persons: [ADMIN.person] } },
    'GET /api/system/info': { body: { admin_contact_email: null, features: { money: true } } },
    'GET /api/system/maintenance': { body: { active: false, until: null } },
    'GET /api/settings/nav': { body: NAV },
    'GET /api/settings/admin/branches': { body: [BRANCH] },
    'GET /api/settings/money/branches': {
      body: {
        centres: [{ id: CENTRE, code: '20', name: 'Senica' }],
        warehouses: [
          { id: WH, code: '20', name: 'Senica' },
          { id: 'w-99', code: '99', name: 'Externý sklad' },
        ],
        branches: [
          {
            id: 'b-se',
            name: 'Pobočka Senica',
            centre_id: CENTRE,
            centre_missing: false,
            reports: {},
            warehouse_id: null,
          },
        ],
      },
    },
    'PUT /api/settings/money/branches/b-se': (body) => {
      saved.push(body);
      return { body: { id: 'b-se', name: 'Pobočka Senica', centre_id: CENTRE, centre_missing: false, reports: {} } };
    },
    'GET /api/settings/money/branches/b-se/dl-template': {
      body: { centre_set: true, template: TPL('n-1', 'DLP0412/2026'), money_available: true },
    },
    'GET /api/settings/money/branches/b-se/dl-templates': {
      body: [
        {
          id: 'n-2',
          number: 'DLP0420/2026',
          supplier: 'Iný dodávateľ',
          issued_on: '2026-11-21',
          koncept: true,
          by_smart_mail: true,
          selected: false,
        },
        {
          id: 'n-1',
          number: 'DLP0412/2026',
          supplier: 'Fiktívny dodávateľ s.r.o.',
          issued_on: '2026-11-18',
          koncept: false,
          by_smart_mail: false,
          selected: true,
        },
        {
          id: 'n-0',
          number: 'DLP0400/2026',
          supplier: 'Tretí dodávateľ',
          issued_on: '2026-11-10',
          koncept: false,
          by_smart_mail: false,
          selected: false,
        },
      ],
    },
    'PUT /api/settings/money/branches/b-se/dl-template': (body) => {
      picked = body;
      return { body: { centre_set: true, template: TPL('n-0', 'DLP0400/2026'), money_available: true } };
    },
    'POST /api/settings/money/branches/b-se/verify': {
      body: {
        rows: [
          { id: 'centre', ok: true, detail: null },
          { id: 'warehouse', ok: true, detail: null },
          { id: 'price_list', ok: false, detail: null },
          { id: 'series', ok: true, detail: null },
          { id: 'template', ok: true, detail: null },
        ],
        template: TPL('n-0', 'DLP0400/2026'),
      },
    },
  });
  // 2026-11-25: the second template for foreign suppliers (0 % VAT) — not set at first, picked by its number
  const foreignPuts: unknown[] = [];
  const asked: string[] = [];
  const FOREIGN = {
    ...TPL('n-719', '302600719'),
    supplier: 'Fiktívny EU dodávateľ s.r.o.',
    vat_rate: '23',
    price_type: 2,
  };
  await page.route('**/api/settings/money/branches/b-se/dl-template**', async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const body = req.postDataJSON() as { kind?: string } | null;
    if (req.method() === 'GET' && url.searchParams.get('kind') === 'foreign') {
      return route.fulfill({ json: { centre_set: true, template: null, money_available: true } });
    }
    if (req.method() === 'PUT' && body?.kind === 'foreign') {
      foreignPuts.push(body);
      return route.fulfill({ json: { centre_set: true, template: FOREIGN, money_available: true } });
    }
    if (req.method() === 'DELETE') {
      return route.fulfill({ json: { centre_set: true, template: null, money_available: true } });
    }
    return route.fallback();
  });
  await page.route('**/api/settings/money/branches/b-se/dl-templates?**', async (route) => {
    const url = new URL(route.request().url());
    const number = url.searchParams.get('number');
    if (url.searchParams.get('kind') !== 'foreign') return route.fallback();
    asked.push(number ?? '');
    const row = { id: 'n-719', number: '302600719', supplier: 'Fiktívny EU dodávateľ s.r.o.', issued_on: '2026-03-02' };
    return route.fulfill({
      json: number === '302600719' ? [{ ...row, koncept: false, by_smart_mail: false, selected: false }] : [],
    });
  });
  await page.goto('/settings/branches/money');
  const panel = page.getByTestId('settings-branch-money');
  await panel.getByTestId('branch-warehouse').selectOption(WH);
  await panel.getByRole('button', { name: 'Uložiť' }).click();
  await expect.poll(() => saved).toEqual([{ centre_id: CENTRE, reports: expect.anything(), warehouse_id: WH }]);
  const card = panel.getByTestId('branch-dl-template');
  await expect(card.getByTestId('branch-dl-template-number')).toHaveText('DLP0412/2026');
  // pilot 2026-11-23: the card says which branch the template note is from
  await expect(card.getByTestId('branch-dl-template-origin')).toHaveText(
    'Doklad strediska 20 – Senica · číselný rad DLP SE – Dodacie listy prijaté Senica',
  );
  await card.getByRole('button', { name: 'Vybrať iný' }).click();
  const list = card.getByTestId('branch-dl-template-list');
  await expect(list).toContainText('zo Smart Mail');
  await list.getByRole('button', { name: /DLP0400\/2026/ }).click();
  await expect(card.getByTestId('branch-dl-template-number')).toHaveText('DLP0400/2026');
  expect(picked).toEqual({ note_id: 'n-0', kind: 'main' });
  await panel.getByTestId('branch-verify').click();
  const result = panel.getByTestId('branch-verify-result');
  await expect(result).toContainText('Vzorový dodací list');
  await expect(result).toContainText('Cenník pobočky');
  const foreign = panel.getByTestId('branch-dl-template-foreign');
  await expect(foreign).toContainText('Vzor pre zahraničných dodávateľov (0 % DPH)');
  await expect(foreign).toContainText('Nenastavený');
  await foreign.getByRole('button', { name: 'Vybrať vzor' }).click();
  await foreign.getByTestId('branch-dl-template-number-search').fill('302600719');
  await foreign.getByRole('button', { name: 'Hľadať' }).click();
  await foreign.getByRole('button', { name: /302600719/ }).click();
  await expect(foreign.getByTestId('branch-dl-template-number')).toHaveText('302600719');
  await expect(foreign.getByTestId('branch-dl-template-vat')).toHaveText(
    'Sadzba DPH položky 23 % · typ ceny „Iba základ“',
  );
  expect(foreignPuts).toEqual([{ note_id: 'n-719', kind: 'foreign' }]);
  expect(asked.at(-1)).toBe('302600719');
  await shot(page, 'issue247-W12-11e-template-desktop');
  await foreign.getByTestId('branch-dl-template-remove').click();
  await expect(foreign).toContainText('Nenastavený');
});

// pilot 2026-11-23: „Originál dokladu“ opens the W2l preview (an iframe was blocked → the browser downloaded the file)
const PDF = readFileSync(fileURLToPath(new URL('./assets/preview-2pages.pdf', import.meta.url)));

test('W6h: „Originál dokladu“ opens the PDF in the preview, not a download', async ({ page }) => {
  await mockApi(page, { ...BASE, 'GET /api/purchasing/documents/d-1': { body: detail() } });
  await page.route('**/api/purchasing/documents/d-1/file', (route) =>
    route.fulfill({
      body: PDF,
      contentType: 'application/pdf',
      headers: { 'Content-Disposition': 'attachment; filename="FA-2611452.pdf"' },
    }),
  );
  await open(page, false);
  await page.getByTestId('w6h-original').click();
  const box = page.getByTestId('attachment-lightbox');
  await expect(box).toBeVisible();
  await expect(box).toContainText('FA-2611452.pdf');
  await expect(box.getByTestId('pdf-page')).toHaveText('Strana 1 / 2');
  await expect(box.getByTestId('pdf-page-view')).toHaveAttribute('data-rendered', '1');
  await shot(page, 'w6h-original-preview-desktop');
  await page.keyboard.press('Escape');
  await expect(box).toHaveCount(0);
});

test('W6h: an order confirmation is hidden with „Nie je faktúra – skryť“', async ({ page }) => {
  let hidden = 0;
  await mockApi(page, {
    ...BASE,
    'GET /api/purchasing/documents/d-1': { body: detail() },
    'POST /api/purchasing/documents/d-1/ignore': () => {
      hidden += 1;
      return { body: { ...detail({ status: 'ignored' }), items: undefined } };
    },
    'GET /api/purchasing/documents': { body: { items: [], total: 0 } },
  });
  await open(page, false);
  await page.getByTestId('w6h-hide').click();
  await expect.poll(() => hidden).toBe(1);
  await expect(page.getByText('Doklad je skrytý.')).toBeVisible();
  await expect(page).toHaveURL(/\/docs\/delivery-notes$/);
});

// pilot 2026-11-24: the koncept was deleted in Money → „Koncept som zmazal v Money“ puts the document back in review
test('W6h: a koncept deleted in Money goes back to review', async ({ page }) => {
  let sent: unknown = null;
  let calls = 0;
  await mockApi(page, {
    ...BASE,
    'GET /api/purchasing/documents/d-1': () => ({ body: calls >= 2 ? detail({ version: 5 }) : created() }),
    'POST /api/purchasing/documents/d-1/reopen': (body) => {
      sent = body;
      calls += 1;
      return calls === 1
        ? { status: 409, body: { detail: { code: 'still_in_money', number: 'DLP0412/2026' } } }
        : { body: detail({ version: 5 }) };
    },
  });
  await open(page, false);
  const banner = page.getByTestId('w6h-write-banner');
  await banner.getByRole('button', { name: 'Koncept som zmazal v Money' }).click();
  await expect(page.getByText('Koncept DLP0412/2026 je v Money stále – najprv ho zmažte v Money.')).toBeVisible();
  await banner.getByRole('button', { name: 'Koncept som zmazal v Money' }).click();
  await expect(page.getByText('Koncept v Money už nie je – doklad je opäť na kontrolu.')).toBeVisible();
  expect(sent).toEqual({ version: 4 });
  await expect(page.getByTestId('w6h-create')).toBeVisible();
});
