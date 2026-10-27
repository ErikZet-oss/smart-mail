import { expect, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

const SIGNED_IN = { 'GET /api/auth/me': { body: ME }, 'GET /api/auth/persons': { body: ME_PICKER } };

const BOOKS = [
  { id: 'book-personal', kind: 'personal', name: 'Osobné adresy' },
  { id: 'book-shared', kind: 'shared', name: 'Zdieľané' },
];

const CONTACTS = [
  {
    id: 'c1',
    address_book_id: 'book-personal',
    display_name: 'Ján Novák',
    first_name: 'Ján',
    last_name: 'Novák',
    organization: 'ABC Stav s.r.o.',
    notes: 'Preferuje faktúry e-mailom.',
    emails: [{ email: 'jan.novak@smartmail.test', type: 'work' }],
    phones: [{ number: '+421900000000', type: 'work' }],
    group_ids: [] as string[],
  },
];

const SEARCH_HIT = {
  q: 'faktúra',
  scope: 'all',
  fields: ['full'],
  total: 1,
  oldest_downloaded_at: '2024-03-15T10:00:00Z',
  messages: [
    {
      id: 'm1',
      folder_id: 'f1',
      mailbox_id: 'mb-1',
      subject: 'Faktúra 2026-01',
      from_name: 'Ján Novák',
      from_email: 'jan@firma.sk',
      preview: 'Posielam faktúru',
      received_at: '2026-10-20T09:00:00Z',
      rank: 0.5,
    },
  ],
};

test.describe('Phase 1g — contacts, search, palette', () => {
  test('W9 contacts personal list and detail', async ({ page }) => {
    await mockApi(page, {
      ...SIGNED_IN,
      'GET /api/contacts/books': { body: BOOKS },
      'GET /api/contacts/books/book-personal/contacts': { body: CONTACTS },
      'GET /api/contacts/books/book-personal/groups': { body: [] },
    });
    await page.goto('/contacts/personal');
    await expect(page.getByRole('heading', { name: 'Kontakty' })).toBeVisible();
    await expect(page.getByText('Ján Novák').first()).toBeVisible();
    await expect(page.getByText('jan.novak@smartmail.test').first()).toBeVisible();
    await shot(page, 'phase1g-W9-personal');
  });

  test('W9 empty state', async ({ page }) => {
    await mockApi(page, {
      ...SIGNED_IN,
      'GET /api/contacts/books': { body: BOOKS },
      'GET /api/contacts/books/book-personal/contacts': { body: [] },
      'GET /api/contacts/books/book-personal/groups': { body: [] },
    });
    await page.goto('/contacts/personal');
    await expect(page.getByText('Zatiaľ žiadne kontakty')).toBeVisible();
    await shot(page, 'phase1g-W9-empty');
  });

  test('W9 import dialog', async ({ page }) => {
    await mockApi(page, {
      ...SIGNED_IN,
      'GET /api/contacts/books': { body: BOOKS },
      'GET /api/contacts/books/book-personal/contacts': { body: CONTACTS },
      'GET /api/contacts/books/book-personal/groups': { body: [] },
    });
    await page.goto('/contacts/personal/c1');
    await page.getByRole('button', { name: 'Import' }).click();
    await expect(page.getByRole('heading', { name: 'Import' })).toBeVisible();
    await expect(page.getByText(/vCard/)).toBeVisible();
    await shot(page, 'phase1g-W9-import');
  });

  test('W10 search results and corpus banner', async ({ page }) => {
    await mockApi(page, {
      ...SIGNED_IN,
      'GET /api/search': { body: SEARCH_HIT },
    });
    await page.goto('/search?q=fakt%C3%BAra&field=full&scope=all');
    await expect(page.getByRole('heading', { name: 'Hľadanie' })).toBeVisible();
    await expect(page.getByTestId('search-corpus-banner')).toContainText('Hľadá sa v správach od');
    await expect(page.getByText('Faktúra 2026-01')).toBeVisible();
    await shot(page, 'phase1g-W10-results');
  });

  test('W10 empty state', async ({ page }) => {
    await mockApi(page, {
      ...SIGNED_IN,
      'GET /api/search': {
        body: {
          q: 'xyzzy',
          scope: 'all',
          fields: ['full'],
          total: 0,
          oldest_downloaded_at: '2024-03-15T10:00:00Z',
          messages: [],
        },
      },
    });
    await page.goto('/search?q=xyzzy');
    await expect(page.getByTestId('search-empty')).toContainText('Nič sme nenašli');
    await expect(page.getByTestId('search-empty')).toContainText('Nerez = A2/A4');
    await shot(page, 'phase1g-W10-empty');
  });

  test('W11 command palette basic groups only', async ({ page }) => {
    await mockApi(page, { ...SIGNED_IN });
    await page.goto('/mail/default/inbox');
    await expect(page.getByRole('navigation', { name: 'Hlavná navigácia' })).toBeVisible();
    await page.evaluate(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true }));
    });
    const palette = page.getByTestId('command-palette');
    await expect(palette).toBeVisible();
    await expect(palette.getByText('Príkazy')).toBeVisible();
    await expect(palette.getByText('E-maily')).toBeVisible();
    await expect(palette.getByText('Kontakty').first()).toBeVisible();
    await expect(palette.getByText('Firmy')).toHaveCount(0);
    await expect(palette.getByText('Doklady')).toHaveCount(0);
    await expect(palette.getByText('Asistent')).toHaveCount(0);
    await shot(page, 'phase1g-W11-palette');

    await page.locator('[data-testid="command-palette"] input').fill('podpis');
    // "podpis" matches nothing in basic palette — empty or filtered; still no Firmy/Doklady/Asistent
    await expect(palette.getByText('Firmy')).toHaveCount(0);
    await shot(page, 'phase1g-W11-search');
  });
});
