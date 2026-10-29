import AxeBuilder from '@axe-core/playwright';
import { expect, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

const SIGNED_IN = { 'GET /api/auth/me': { body: ME }, 'GET /api/auth/persons': { body: ME_PICKER } };

const VIEWER_ME = {
  ...ME,
  person: { ...ME.person, role: 'viewer' },
  read_only: true,
};

const BOOKS = [
  { id: 'book-personal', kind: 'personal', name: 'Osobné adresy' },
  { id: 'book-shared', kind: 'shared', name: 'Zdieľané' },
];

const CONTACT = {
  id: 'c1',
  address_book_id: 'book-shared',
  display_name: 'Ján Novák',
  first_name: 'Ján',
  last_name: 'Novák',
  organization: 'ABC Stav s.r.o.',
  notes: null as string | null,
  emails: [{ email: 'jan.novak@smartmail.test', type: 'work' }],
  phones: [] as { number: string; type: string }[],
  group_ids: [] as string[],
};

async function expectNoSeriousAxe(page: import('@playwright/test').Page) {
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze();
  const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
  expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
}

test.describe('Phase 1h-e — import debts, empty states, axe', () => {
  test('W9 empty list illustration', async ({ page }) => {
    await mockApi(page, {
      ...SIGNED_IN,
      'GET /api/contacts/books': { body: BOOKS },
      'GET /api/contacts/books/book-personal/contacts': { body: [] },
      'GET /api/contacts/books/book-personal/groups': { body: [] },
    });
    await page.goto('/contacts/personal');
    await expect(page.getByTestId('contacts-empty')).toContainText('Zatiaľ žiadne kontakty');
    await shot(page, 'phase1h-e-W9-empty');
  });

  test('W9 viewer on shared book hides edit/delete/import', async ({ page }) => {
    await mockApi(page, {
      'GET /api/auth/me': { body: VIEWER_ME },
      'GET /api/auth/persons': {
        body: { ...ME_PICKER, persons: [VIEWER_ME.person], current_person_id: VIEWER_ME.person.id },
      },
      'GET /api/contacts/books': { body: BOOKS },
      'GET /api/contacts/books/book-shared/contacts': { body: [CONTACT] },
      'GET /api/contacts/books/book-shared/groups': { body: [] },
    });
    await page.goto('/contacts/shared/c1');
    await expect(page.getByText('Ján Novák').first()).toBeVisible();
    await expect(page.getByRole('button', { name: 'Upraviť' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Vymazať' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Import' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Export' })).toBeVisible();
    await shot(page, 'phase1h-e-W9-viewer-shared');
  });

  test('W10 empty tips + illustration', async ({ page }) => {
    await mockApi(page, {
      ...SIGNED_IN,
      'GET /api/search': {
        body: {
          q: 'podložky M14 nerez Klaus',
          scope: 'current',
          fields: ['full'],
          total: 0,
          oldest_downloaded_at: '2024-03-15T10:00:00Z',
          messages: [],
        },
      },
    });
    await page.goto('/search?q=podlo%C5%BEky%20M14%20nerez%20Klaus&scope=current');
    const empty = page.getByTestId('search-empty');
    await expect(empty).toContainText('Nič sme nenašli');
    await expect(empty).toContainText('Nerez = A2/A4');
    await expect(empty.getByRole('button', { name: 'Hľadať vo všetkých schránkach' })).toBeVisible();
    await shot(page, 'phase1h-e-W10-empty');
  });

  test('axe: no serious issues on main Phase-1 screens', async ({ page }) => {
    await mockApi(page, {
      ...SIGNED_IN,
      'GET /api/contacts/books': { body: BOOKS },
      'GET /api/contacts/books/book-personal/contacts': { body: [] },
      'GET /api/contacts/books/book-personal/groups': { body: [] },
      'GET /api/search': {
        body: { q: 'x', scope: 'all', fields: ['full'], total: 0, oldest_downloaded_at: null, messages: [] },
      },
      // without it the settings page got a 401 and could end on /login before the axe check (#62)
      'GET /api/settings/preferences': {
        body: {
          ui: { theme: 'system', classic: false },
          list: { density: 'compact', mode: 'list', page_size: 50, show_ai_summary: true },
          reading: {},
          composing: { undo_send_seconds: 10 },
          shortcuts: {},
        },
      },
    });

    await page.goto('/mail/default/inbox');
    await expect(page.getByRole('navigation', { name: 'Hlavná navigácia' })).toBeVisible();
    await expectNoSeriousAxe(page);

    await page.goto('/contacts/personal');
    await expect(page.getByTestId('contacts-empty')).toBeVisible();
    await expectNoSeriousAxe(page);

    await page.goto('/search?q=x');
    await expect(page.getByTestId('search-empty')).toBeVisible();
    await expectNoSeriousAxe(page);

    await page.goto('/settings/preferences');
    await expect(page.getByText(/Nastavenia/i).first()).toBeVisible({ timeout: 10_000 });
    await expectNoSeriousAxe(page);
  });
});
