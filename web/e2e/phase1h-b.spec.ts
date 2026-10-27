import { DEFAULT_PREFS, expect, foldersView, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

const SIGNED_IN = { 'GET /api/auth/me': { body: ME }, 'GET /api/auth/persons': { body: ME_PICKER } };

const CONTACT = {
  id: 'c-1',
  display_name: 'Ján Novák',
  first_name: 'Ján',
  last_name: 'Novák',
  organization: 'ABC Stav',
  notes: null,
  emails: [{ email: 'novak@abcstav.example', type: 'work' }],
  phones: [{ number: '+421900111222', type: 'mobile' }],
  group_ids: [] as string[],
};

async function mockShell(page: import('@playwright/test').Page) {
  await mockApi(page, {
    ...SIGNED_IN,
    'GET /api/mail/prefs': { body: DEFAULT_PREFS },
    'PUT /api/mail/prefs': { body: DEFAULT_PREFS },
    'GET /api/contacts/books': {
      body: [
        { id: 'book-p', kind: 'personal', name: 'Osobné' },
        { id: 'book-s', kind: 'shared', name: 'Zdieľané' },
      ],
    },
    'GET /api/contacts/books/book-p/contacts': { body: [CONTACT] },
    'GET /api/contacts/books/book-p/groups': { body: [] },
    'GET /api/contacts/books/book-s/contacts': { body: [] },
    'GET /api/contacts/books/book-s/groups': { body: [] },
    'GET /api/search': {
      body: {
        total: 1,
        messages: [
          {
            id: 'm-1',
            thread_id: 't-1',
            subject: 'Faktúra 2026123',
            from_name: 'Ján Novák',
            from_email: 'novak@abcstav.example',
            preview: 'Prosím o kópiu…',
            received_at: '2026-10-26T07:42:00Z',
          },
        ],
        oldest_downloaded_at: '2026-01-01T00:00:00Z',
      },
    },
    'GET /api/settings/nav': {
      body: {
        sections: [
          { id: '01', path: 'preferences', title: 'Nastavenia', subs: [] },
          {
            id: '03',
            path: 'identity',
            title: 'Identity',
            subs: [{ id: '03b', path: 'profile', title: 'Môj profil' }],
          },
          { id: '04', path: 'responses', title: 'Odpovede', subs: [] },
          { id: '06', path: 'vacation', title: 'Mimo kancelárie', subs: [] },
          { id: '09', path: 'security', title: 'Bezpečnosť', subs: [] },
        ],
      },
    },
    'GET /api/settings/preferences': { body: DEFAULT_PREFS },
    'GET /api/settings/profile': {
      body: {
        id: ME.person.id,
        first_name: ME.person.first_name,
        last_name: ME.person.last_name,
        function: null,
        phone: null,
        mobile: null,
        personal_email: null,
        languages: ['sk'],
        style_guide: null,
        role: ME.person.role,
        signature_preview_html: '<p>Jana</p>',
      },
    },
    'GET /api/mail/mailboxes/default/folders': { body: foldersView() },
  });
}

test.describe('Phase 1h-b: M8 M9 M15 M18', () => {
  test('M8 search full screen @mobile', async ({ page }, info) => {
    test.skip(info.project.name !== 'mobile', 'mobile');
    await mockShell(page);
    await page.goto('/search');
    await expect(page.getByTestId('screen-m8')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Hľadanie' })).toBeVisible();
    await page.getByLabel('Hľadanie').fill('faktúra');
    await page.getByLabel('Hľadanie').press('Enter');
    await expect(page.getByText('Faktúra 2026123')).toBeVisible();
    await shot(page, 'phase1hb-M8-search');
  });

  test('M9 settings index Phase-1 subset @mobile', async ({ page }, info) => {
    test.skip(info.project.name !== 'mobile', 'mobile');
    await mockShell(page);
    await page.goto('/settings');
    await expect(page.getByTestId('mobile-settings-index')).toBeVisible();
    await expect(page.getByText('Len na počítači')).toBeVisible();
    await expect(page.getByRole('link', { name: /Môj profil/ })).toBeVisible();
    await expect(page.getByRole('link', { name: /Vzhľad/ })).toBeVisible();
    await expect(page.getByText('AI asistent')).toHaveCount(0);
    await expect(page.getByText('Notifikácie')).toHaveCount(0);
    await shot(page, 'phase1hb-M9-settings');
    await page.getByRole('link', { name: /Vzhľad/ }).click();
    await expect(page.getByTestId('mobile-settings-section')).toBeVisible();
    await expect(page.getByText('Oneskorenie odoslania')).toBeVisible();
    await shot(page, 'phase1hb-M9-prefs');
  });

  test('M15 contacts list and detail @mobile', async ({ page }, info) => {
    test.skip(info.project.name !== 'mobile', 'mobile');
    await mockShell(page);
    await page.goto('/contacts/personal');
    await expect(page.getByTestId('screen-m15')).toBeVisible();
    await expect(page.getByText('Ján Novák')).toBeVisible();
    await shot(page, 'phase1hb-M15-list');
    await page.getByRole('button', { name: /Ján Novák/ }).click();
    await expect(page.getByTestId('screen-m15-detail')).toBeVisible();
    await expect(page.getByRole('link', { name: /novak@abcstav\.example/i })).toBeVisible();
    await shot(page, 'phase1hb-M15-detail');
  });

  test('M18 Viac Phase-1 items only @mobile', async ({ page }, info) => {
    test.skip(info.project.name !== 'mobile', 'mobile');
    await mockShell(page);
    await page.goto('/mail/default/inbox');
    await page.getByRole('button', { name: 'Viac' }).click();
    const more = page.getByTestId('screen-m18');
    await expect(more).toBeVisible();
    await expect(more.getByRole('heading', { name: 'Viac' })).toBeVisible();
    await expect(more.getByRole('link', { name: 'Kontakty' })).toBeVisible();
    await expect(more.getByRole('link', { name: 'Nastavenia' })).toBeVisible();
    await expect(more.getByRole('switch', { name: 'Tmavý režim' })).toBeVisible();
    await expect(more.getByRole('button', { name: 'Odhlásiť' })).toBeVisible();
    await expect(more.getByText('O systéme')).toHaveCount(0);
    // Bottom nav Phase-1: no Dnes / Doklady tabs
    await expect(page.getByTestId('bottom-nav').getByText('Dnes')).toHaveCount(0);
    await expect(page.getByTestId('bottom-nav').getByText('Doklady')).toHaveCount(0);
    await shot(page, 'phase1hb-M18-more');
  });
});
