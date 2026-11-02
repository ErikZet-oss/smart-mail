import { expect, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

// Phase 3e — W8b Upomienky (FEATURE_MONEY). All companies, invoices and amounts are fictional.

const ACCOUNTING = { ...ME, person: { ...ME.person, role: 'accounting' } };
const company = (n: number) => ({
  money_id: `0000000${n}-0000-4000-8000-00000000000${n}`,
  name: `Fiktívny dlžník ${n} s.r.o.`,
  code: `D${n}`,
  ico: null,
  dic: null,
  icdph: null,
  email: n === 3 ? null : `uctaren@dlznik${n}.example`,
  discount_pct: null,
  due_days: 14,
});
const invoice = (number: string, due: string, remaining: string) => ({
  id: number,
  kind: 'invoice',
  number,
  due_on: due,
  issued_on: due,
  total: remaining,
  remaining,
});
const DEBTORS = [
  {
    company: company(1),
    contact: 'uctaren@dlznik1.example',
    overdue_total: '1520.4',
    invoice_count: 2,
    oldest_days: 91,
    last_reminder_at: null,
    invoices: [invoice('FV2600010', '2026-08-01', '1500'), invoice('FV2600011', '2026-09-20', '20.4')],
  },
  {
    company: company(3),
    contact: null,
    overdue_total: '10',
    invoice_count: 1,
    oldest_days: 30,
    last_reminder_at: null,
    invoices: [invoice('FV2600030', '2026-10-01', '10')],
  },
];

const BASE = {
  'GET /api/auth/me': { body: ACCOUNTING },
  'GET /api/auth/persons': { body: { ...ME_PICKER, persons: [ACCOUNTING.person] } },
  'GET /api/system/info': { body: { admin_contact_email: null, features: { money: true } } },
};

test('3e W8b: debtors, prepare one reminder per customer, open the draft @mobile', async ({ page }, info) => {
  const prepared: unknown[] = [];
  await mockApi(page, {
    ...BASE,
    'GET /api/money/reminders': { body: DEBTORS },
    'POST /api/money/reminders/drafts': (payload) => {
      prepared.push(payload);
      return { body: [{ company_money_id: company(1).money_id, draft_id: 'd-r1', error: null }] };
    },
    'GET /api/money/reminders/history': {
      body: [
        {
          at: '2026-10-31T08:00:00Z',
          company_money_id: company(1).money_id,
          company_name: company(1).name,
          draft_id: 'd-r1',
          draft_status: 'editing',
          tone: 'firm',
          invoices: ['FV2600010', 'FV2600011'],
        },
      ],
    },
  });
  await page.goto('/docs/reminders');
  const table = page.getByTestId('reminders-table');
  await expect(table).toContainText('Fiktívny dlžník 1 s.r.o.');
  await expect(table).toContainText('1 520,40 €');
  await expect(table).toContainText('91 dní');
  await expect(table.getByLabel('Vybrať Fiktívny dlžník 3 s.r.o.')).toBeDisabled(); // no e-mail in Money
  await expect(table).toContainText('chýba e-mail firmy v Money');
  await shot(page, `phase3e-w8b-${info.project.name}`);
  await table.getByLabel('Vybrať Fiktívny dlžník 1 s.r.o.').check();
  await page.getByRole('radio', { name: 'Dôrazná' }).click();
  await page.getByRole('button', { name: 'Pripraviť upomienku (1)' }).click();
  await expect.poll(() => prepared).toEqual([{ company_money_ids: [company(1).money_id], tone: 'firm' }]);
  const results = page.getByTestId('reminders-results');
  await expect(results.getByRole('link', { name: 'Otvoriť koncept' })).toHaveAttribute('href', '/compose/d-r1');
  await page.getByRole('tab', { name: 'Odoslané upomienky' }).click();
  await expect(page.getByTestId('reminders-history')).toContainText('koncept – čaká na odoslanie');
});

test('3e W8b: Money down and the empty state', async ({ page }) => {
  let down = true;
  await mockApi(page, {
    ...BASE,
    'GET /api/money/reminders': () =>
      down ? { status: 503, body: { detail: { code: 'money_unavailable' } } } : { body: [] },
  });
  await page.goto('/docs/reminders');
  await expect(page.getByRole('alert')).toContainText('Money je teraz nedostupné');
  down = false;
  await page.getByRole('button', { name: 'Skúsiť znova' }).click();
  await expect(page.getByTestId('reminders-empty')).toContainText('Nikto nemá faktúry po splatnosti');
});

test('3e Doklady is in the rail only with FEATURE_MONEY', async ({ page }) => {
  await mockApi(page, {
    ...BASE,
    'GET /api/system/info': { body: { admin_contact_email: null, features: { money: false } } },
  });
  await page.goto('/docs/reminders');
  await expect(page).toHaveURL(/\/404/);
  await expect(page.getByRole('link', { name: 'Doklady' })).toHaveCount(0);
});

test('#193 desktop rail order: E-mail, Doklady, Kontakty, Nastavenia', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop', 'desktop rail');
  await mockApi(page, {
    ...BASE,
    'GET /api/money/reminders': { body: DEBTORS },
    'GET /api/money/reminders/history': { body: [] },
  });
  await page.goto('/docs/reminders');
  const rail = page.getByRole('navigation', { name: 'Hlavná navigácia' });
  await expect(rail.getByRole('link', { name: 'Doklady' })).toBeVisible();
  const names = await rail
    .locator('a')
    .evaluateAll((els) => els.map((e) => (e.getAttribute('aria-label') ?? '').split(' (')[0] ?? ''));
  const order = names.filter((n) => ['E-mail', 'Doklady', 'Kontakty', 'Nastavenia'].includes(n));
  expect(order).toEqual(['E-mail', 'Doklady', 'Kontakty', 'Nastavenia']);
});

test('3e W8b as in Figma: Doklady tabs, filters, last reminder with tone, contact name', async ({ page }, info) => {
  const rows = [
    {
      ...DEBTORS[0],
      last_reminder_at: '2026-10-02T08:00:00Z',
      last_reminder_tone: 'polite',
      contact_name: 'Eva Účtovná',
    },
    DEBTORS[1],
  ];
  await mockApi(page, { ...BASE, 'GET /api/money/reminders': { body: rows } });
  await page.goto('/docs/reminders');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Doklady');
  // Phase 4a: accounting may upload supplier documents and open Dodacie listy (W6e)
  await expect(page.getByRole('button', { name: 'Nahrať doklad' })).toBeEnabled();
  const tabs = page.getByRole('navigation', { name: 'Doklady' });
  await expect(tabs.getByRole('link', { name: 'Dodacie listy' })).toHaveAttribute('href', '/docs/delivery-notes');
  await expect(tabs.getByText('Objednávky')).toHaveAttribute('aria-disabled', 'true');
  await expect(tabs.getByText('Upomienky')).toHaveAttribute('aria-current', 'page');
  await expect(page.getByRole('tab', { name: 'Po splatnosti (2)' })).toHaveAttribute('aria-selected', 'true');
  const table = page.getByTestId('reminders-table');
  await expect(table).toContainText('2. 10. 2026 (zdvorilá)');
  await expect(table).toContainText('Eva Účtovná · uctaren@dlznik1.example');
  await shot(page, `phase3e-w8b-figma-${info.project.name}`);
  await page.getByRole('button', { name: 'Bez upomienky' }).click();
  await expect(table).not.toContainText('Fiktívny dlžník 1 s.r.o.');
  await expect(table).toContainText('Fiktívny dlžník 3 s.r.o.');
  await page.getByRole('button', { name: 'Bez upomienky' }).click();
  await page.getByLabel('Suma').selectOption('1000');
  await expect(table).toContainText('Fiktívny dlžník 1 s.r.o.');
  await expect(table).not.toContainText('Fiktívny dlžník 3 s.r.o.');
  await page.getByPlaceholder('Hľadať zákazníka…').fill('nikto');
  await expect(table).toContainText('Filtru nezodpovedá žiadny zákazník.');
});

// #193 Doklady on mobile (Figma M13 `85:3245`): bottom nav E-mail · Doklady · Kontakty · Viac, 360 px without overflow.
test.describe('#193 Doklady on mobile @mobile', () => {
  test.use({ viewport: { width: 360, height: 780 } });

  test('#193 bottom nav order, Doklady active on /docs/reminders, nothing outside 360 px', async ({ page }, info) => {
    test.skip(info.project.name !== 'mobile', 'mobile frame');
    await mockApi(page, {
      ...BASE,
      'GET /api/money/reminders': { body: DEBTORS },
      'GET /api/money/reminders/history': { body: [] },
    });
    await page.goto('/docs/reminders');
    const nav = page.getByTestId('bottom-nav');
    await expect(nav.getByRole('link', { name: 'Doklady' })).toHaveAttribute('aria-current', 'page');
    const labels = await nav.locator('a, button').evaluateAll((els) => els.map((e) => e.getAttribute('aria-label')));
    expect(labels).toEqual(['E-mail', 'Doklady', 'Kontakty', 'Viac']);
    await expect(page.getByTestId('screen-w8b')).toContainText('Fiktívny dlžník 1 s.r.o.');
    const outside = await page.evaluate(() => {
      const out: string[] = [];
      document.querySelectorAll('[data-testid=screen-w8b] *').forEach((el) => {
        const r = (el as HTMLElement).getBoundingClientRect();
        const scroller = (el as HTMLElement).closest('nav, [data-scroll-x]');
        if (!scroller && r.width > 0 && r.right > window.innerWidth + 0.5)
          out.push(el.tagName + ':' + (el.textContent ?? '').slice(0, 30));
      });
      return { out: out.slice(0, 10), overflow: document.documentElement.scrollWidth - window.innerWidth };
    });
    expect(outside.overflow).toBeLessThanOrEqual(0);
    expect(outside.out).toEqual([]);
    await shot(page, 'issue193-M13-reminders-360');
  });

  test('#193 no Doklady in the bottom nav without a role or without FEATURE_MONEY', async ({ page }, info) => {
    test.skip(info.project.name !== 'mobile', 'mobile frame');
    const WAREHOUSE = { ...ME, person: { ...ME.person, role: 'viewer' } }; // no Doklady tab for viewer
    await mockApi(page, {
      ...BASE,
      'GET /api/auth/me': { body: WAREHOUSE },
      'GET /api/auth/persons': { body: { ...ME_PICKER, persons: [WAREHOUSE.person] } },
    });
    await page.goto('/docs/reminders'); // a viewer only gets the role banner here
    await expect(page.getByText('Upomienky pripravuje účtovníctvo, obchod alebo správca.')).toBeVisible();
    const nav = page.getByTestId('bottom-nav');
    await expect(nav.getByRole('link', { name: 'Kontakty' })).toBeVisible();
    await expect(nav.getByRole('link', { name: 'Doklady' })).toHaveCount(0);
  });
});
