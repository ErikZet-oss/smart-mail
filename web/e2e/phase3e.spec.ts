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
