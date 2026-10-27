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
    // SETTINGS 07 (summaries) landed in Phase 2b; Notifikácie (08) still later.
    await expect(page.getByRole('link', { name: /AI asistent/ })).toBeVisible();
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
    await expect(page.getByRole('button', { name: /novak@abcstav\.example/i })).toBeVisible();
    await expect(page.locator('a[href^="mailto:"]')).toHaveCount(0);
    // Header call icon + detail phone field both use tel:
    await expect(page.locator('a[href^="tel:"]')).toHaveCount(2);
    await shot(page, 'phase1hb-M15-detail');
  });

  test('M15 contact email opens Smart Mail compose (not mailto) @mobile', async ({ page }, info) => {
    test.skip(info.project.name !== 'mobile', 'mobile');
    const draft = {
      id: 'd-contact',
      mailbox_id: 'mb-1',
      mode: 'new',
      identity_id: 'id-1',
      to_addrs: [] as { email: string }[],
      cc_addrs: [] as unknown[],
      bcc_addrs: [] as unknown[],
      subject: '',
      body_html: '<p></p>',
      body_text: '',
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
      attachments: [],
      checks: [],
      updated_at: '2026-10-26T12:00:00Z',
    };
    await mockShell(page);
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
      'POST /api/mail/mailboxes/default/compose': { body: draft },
      'GET /api/mail/compose/d-contact': { body: draft },
      'PATCH /api/mail/compose/d-contact': { body: draft },
      'GET /api/mail/mailboxes/default/identities': {
        body: [
          {
            id: 'id-1',
            display_name: 'Jana Testová',
            email: 'jana@smartsro.sk',
            organization: 'Smart s.r.o.',
            is_default: true,
          },
        ],
      },
      'GET /api/mail/responses': { body: [] },
      'GET /api/mail/mailboxes/default/folders': { body: foldersView() },
    });
    await page.goto('/contacts/personal/c-1');
    await expect(page.getByTestId('screen-m15-detail')).toBeVisible();
    await page.getByRole('button', { name: /novak@abcstav\.example/i }).click();
    await expect(page).toHaveURL(/\/compose/);
    await expect(page.locator('a[href^="mailto:"]')).toHaveCount(0);
    await expect(page.getByLabel('Komu')).toHaveValue(/novak@abcstav\.example/);
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
    const theme = more.getByTestId('m18-theme');
    await expect(theme.getByRole('radio', { name: 'Svetlý' })).toBeVisible();
    await expect(theme.getByRole('radio', { name: 'Tmavý' })).toBeVisible();
    await expect(theme.getByRole('radio', { name: 'Podľa zariadenia' })).toBeVisible();
    await expect(more.getByRole('switch')).toHaveCount(0);
    await expect(more.getByRole('button', { name: 'Odhlásiť' })).toBeVisible();
    // O systéme lands in 1h-c with W15b — assert absence only while this suite stays on 1h-b branch;
    // after merge of 1h-c the item is present (covered by phase1h-c.spec.ts).
    // Bottom nav Phase-1: no Dnes / Doklady tabs
    await expect(page.getByTestId('bottom-nav').getByText('Dnes')).toHaveCount(0);
    await expect(page.getByTestId('bottom-nav').getByText('Doklady')).toHaveCount(0);
    await shot(page, 'phase1hb-M18-more');
  });
});
