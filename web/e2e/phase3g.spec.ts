import { expect, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

// Phase 3g — W9a Zákazník 360 and Money in search / Ctrl+K (FEATURE_MONEY). Fictional data only.

const ID = '11111111-1111-4111-8111-111111111111';
const COMPANY = {
  money_id: ID,
  name: 'Fiktívna firma 360 s.r.o.',
  code: 'F360',
  ico: '36123459',
  dic: '2020000001',
  icdph: 'SK2020000001',
  email: 'info@firma360.example',
  discount_pct: '8',
  due_days: 30,
};
const CARD = {
  company: COMPANY,
  receivables: {
    error: null,
    open_count: 1,
    open_total: '120',
    overdue_count: 0,
    overdue_total: '0',
    oldest_overdue_days: null,
    mixed_currency: false,
    items: [
      {
        id: 'i1',
        kind: 'invoice',
        number: 'FV2600042',
        due_on: '2099-01-01',
        issued_on: '2026-10-01',
        total: '120',
        remaining: '120',
      },
    ],
  },
  orders: {
    error: null,
    items: [{ id: 'o1', number: 'OP260001', issued_on: '2026-10-02', reference: 'OBJ-1', total: '50' }],
  },
  deliveries: { error: null, items: [] },
  activities: { error: 'waiting_for_probe', items: [] },
  persons: [{ money_id: 'p1', name: 'Ján Fiktívny', function: 'nákup', email: 'jan@firma360.example', phone: null }],
};
const BASE = {
  'GET /api/auth/me': { body: ME },
  'GET /api/auth/persons': { body: ME_PICKER },
  'GET /api/system/info': { body: { admin_contact_email: null, features: { money: true } } },
  [`GET /api/money/companies/${ID}/card`]: { body: CARD },
  [`GET /api/money/companies/${ID}/emails`]: { body: [] },
};

test('3g W9a Zákazník 360: tabs Prehľad, E-maily, Doklady, Kontakty @mobile', async ({ page }, info) => {
  await mockApi(page, {
    ...BASE,
    [`GET /api/money/companies/${ID}/emails`]: {
      body: [
        {
          id: 'm1',
          mailbox_id: 'mb1',
          thread_id: 't1',
          subject: 'Kópia faktúry',
          from_name: 'Ján Fiktívny',
          from_email: 'jan@firma360.example',
          received_at: '2026-10-30T07:00:00Z',
          direction: 'in',
        },
      ],
    },
  });
  await page.goto(`/contacts/company/${ID}`);
  const screen = page.getByTestId('screen-w9a');
  await expect(screen.getByRole('heading', { level: 1 })).toHaveText('Fiktívna firma 360 s.r.o.');
  await expect(screen).toContainText('IČO 36123459 · DIČ 2020000001 · IČ DPH SK2020000001');
  await expect(screen).toContainText('120,00 €');
  await shot(page, `phase3g-w9a-${info.project.name}`);
  await screen.getByRole('tab', { name: /^E-maily/ }).click();
  await expect(page).toHaveURL(/tab=emails/);
  await expect(screen.getByTestId('company-mail').getByRole('link')).toHaveAttribute('href', '/mail/mb1/inbox/m1');
  await screen.getByRole('tab', { name: 'Doklady' }).click();
  await expect(screen).toContainText('FV2600042');
  await expect(screen).toContainText('OP260001');
  await screen.getByRole('tab', { name: 'Kontakty (1)' }).click();
  await expect(screen).toContainText('Ján Fiktívny');
  await screen.getByRole('tab', { name: 'Aktivity' }).click();
  await expect(screen).toContainText('Zatiaľ nedostupné – čaká sa na test prepojenia s Money.');
  await expect(screen.getByRole('button', { name: 'Napísať' })).toBeEnabled();
});

test('3g Ctrl+K shows Firmy and Doklady from Money', async ({ page }) => {
  await mockApi(page, {
    ...BASE,
    'GET /api/money/search': {
      body: {
        companies: [COMPANY],
        invoices: [
          {
            id: 'i1',
            kind: 'invoice',
            number: 'FV2600042',
            company_id: ID,
            due_on: null,
            issued_on: null,
            total: '120',
            remaining: '120',
          },
        ],
        invoices_error: null,
      },
    },
  });
  await page.goto(`/contacts/company/${ID}`);
  await expect(page.getByTestId('screen-w9a')).toBeVisible();
  await page.keyboard.press('Control+k');
  const palette = page.getByTestId('command-palette');
  await palette.getByRole('searchbox').fill('fiktív');
  await expect(palette).toContainText('Firmy');
  await expect(palette).toContainText('Fiktívna firma 360 s.r.o.');
  await expect(palette).toContainText('FV2600042');
});
