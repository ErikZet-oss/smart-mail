import AxeBuilder from '@axe-core/playwright';

import { expect, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

/** #203 W4g / M4b Adresár – výber príjemcov (Figma 192:89654, 195:3). Fictional data only. */
const draft = {
  id: 'd-203',
  mailbox_id: 'mb-1',
  mode: 'new',
  identity_id: 'id-1',
  to_addrs: [{ email: 'novak@abcstav.example' }],
  cc_addrs: [],
  bcc_addrs: [],
  subject: 'Ponuka',
  body_html: '<p>Dobrý deň</p>',
  body_text: 'Dobrý deň',
  include_signature: true,
  signature_html_override: null,
  signature_person_id: 'p1',
  priority: 'normal',
  request_mdn: false,
  request_dsn: false,
  save_sent: true,
  status: 'editing',
  scheduled_at: null,
  undo_until: null,
  send_error: null,
  send_error_meta: null,
  attachments: [],
  checks: [],
  updated_at: '2026-11-03T08:00:00Z',
};
const SHARED = [
  ['c1', 'Ján Novák', 'ABC Stav s.r.o.', 'novak@abcstav.example'],
  ['c2', 'Petra Kováčová', 'Fiktívna Fixtech s.r.o.', 'petra.kovacova@fixtech.example'],
  ['c3', 'Klaus Weber', 'Weber Befestigung GmbH', 'k.weber@weber.example'],
  ['c4', 'Lucia Beňová', 'Stavmont s.r.o.', 'benova@stavmont.example'],
].map(([id, name, org, email]) => ({
  id,
  address_book_id: 'b-shared',
  display_name: name,
  first_name: null,
  last_name: null,
  organization: org,
  notes: null,
  emails: [{ email }],
  phones: [],
  group_ids: [],
}));

async function open(page: import('@playwright/test').Page) {
  await mockApi(page, {
    'GET /api/auth/me': { body: ME },
    'GET /api/auth/persons': { body: ME_PICKER },
    'GET /api/mail/mailboxes/default/identities': {
      body: [{ id: 'id-1', display_name: 'Jana Testová', email: 'jana@smartmail.test', is_default: true }],
    },
    'GET /api/mail/responses': { body: [] },
    'GET /api/mail/compose/d-203': { body: draft },
    'GET /api/contacts/picker/summary': {
      body: { recent: 2, personal: 0, shared: 4, branches: 1, money: 4104 },
    },
    'GET /api/contacts/books': {
      body: [
        { id: 'b-personal', kind: 'personal', name: 'Osobné adresy' },
        { id: 'b-shared', kind: 'shared', name: 'Zdieľané' },
      ],
    },
    'GET /api/contacts/books/b-shared/contacts': { body: SHARED },
    'GET /api/contacts/books/b-shared/groups': { body: [] },
    'GET /api/contacts/books/b-personal/contacts': { body: [] },
    'GET /api/contacts/books/b-personal/groups': { body: [] },
    'GET /api/contacts/picker/recent': {
      body: [{ key: 'iny@firma.example', name: 'Iný Odberateľ', email: 'iny@firma.example', organization: null }],
    },
    'GET /api/contacts/picker/branches': { body: [] },
    'GET /api/contacts/picker/money': { status: 503, body: { detail: { code: 'money_unavailable' } } },
  });
  await page.goto('/compose/d-203?mailbox=default');
  await expect(page.getByLabel('Komu', { exact: true })).toHaveValue('novak@abcstav.example');
}

test('#203 W4g/M4b: pick 2 contacts across address books → Komu, no duplicate @mobile', async ({ page }, info) => {
  const mobile = info.project.name !== 'desktop';
  await open(page);
  await page.getByTestId('open-address-picker').first().click();
  const dialog = page.getByRole('dialog', { name: mobile ? 'Adresár' : 'Adresár – vyberte príjemcov' });
  await expect(dialog).toBeVisible();
  // Naposledy použité first, then Zdieľané – the selection is kept across address books
  await dialog.getByTestId('picker-row-iny@firma.example').click();
  if (mobile) await dialog.getByRole('tab', { name: 'Zdieľané' }).click();
  else await dialog.getByTestId('picker-source-shared').click();
  await expect(dialog.getByTestId('picker-list')).toContainText('Petra Kováčová');
  await dialog.getByTestId('picker-row-petra.kovacova@fixtech.example').click();
  await dialog.getByTestId('picker-row-novak@abcstav.example').click(); // already in Komu → not added twice
  if (!mobile) {
    await expect(dialog.getByTestId('picker-count')).toHaveText('Vybrané: 3');
    await expect(dialog.getByTestId('picker-source-money')).toContainText('4 104');
    const axe = await new AxeBuilder({ page })
      .include('[data-testid="address-picker"]')
      .withTags(['wcag2a', 'wcag2aa'])
      .analyze();
    expect(axe.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')).toEqual([]);
  }
  await shot(page, `issue203-${mobile ? 'M4b' : 'W4g'}-${info.project.name}`);
  await (mobile ? dialog.getByTestId('picker-add') : dialog.getByTestId('picker-add-to')).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByLabel('Komu', { exact: true })).toHaveValue(
    'novak@abcstav.example, Iný Odberateľ <iny@firma.example>, Petra Kováčová <petra.kovacova@fixtech.example>',
  );
});

test('#203 W4g: Kópia opens the field, search filters, Money needs 2 letters and may be offline', async ({ page }) => {
  await open(page);
  await page.getByTestId('open-address-picker').first().click();
  const dialog = page.getByRole('dialog', { name: 'Adresár – vyberte príjemcov' });
  await dialog.getByTestId('picker-source-shared').click();
  await dialog.getByTestId('picker-search').fill('weber');
  await expect(dialog.getByTestId('picker-list')).toContainText('Klaus Weber');
  await dialog.getByTestId('picker-row-k.weber@weber.example').click();
  await dialog.getByTestId('picker-search').fill('');
  await dialog.getByTestId('picker-source-money').click();
  await expect(dialog.getByTestId('picker-empty')).toHaveText(
    'Napíšte aspoň 2 znaky – Money – adresár má tisíce kontaktov.',
  );
  await dialog.getByTestId('picker-search').fill('stav');
  await expect(dialog.getByTestId('picker-empty')).toHaveText(
    'Money – adresár je teraz nedostupný. Ostatné adresáre fungujú.',
  );
  await dialog.getByTestId('picker-add-cc').click();
  await expect(page.getByLabel('Kópia', { exact: true })).toHaveValue('Klaus Weber <k.weber@weber.example>');
  // Esc closes without changes
  await page.getByTestId('open-address-picker').first().click();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog', { name: 'Adresár – vyberte príjemcov' })).toHaveCount(0);
});
