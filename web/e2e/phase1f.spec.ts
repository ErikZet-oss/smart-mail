import { expect, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

const SIGNED_IN = { 'GET /api/auth/me': { body: ME }, 'GET /api/auth/persons': { body: ME_PICKER } };

const NAV = {
  sections: [
    {
      id: '01',
      path: 'preferences',
      title: 'Nastavenia',
      subs: [
        { id: '01a', path: 'ui', title: 'Používateľské rozhranie' },
        { id: '01d', path: 'composing', title: 'Vytváranie správ' },
      ],
    },
    { id: '05', path: 'filters', title: 'Filtre', subs: [] },
    { id: '06', path: 'vacation', title: 'Mimo kancelárie', subs: [] },
    { id: '09b', path: 'provider', title: 'Nastavenia e-mail schránky', subs: [] },
  ],
};

test.describe('Phase 1f — settings + W4e', () => {
  test('W12 preferences UI', async ({ page }) => {
    await mockApi(page, {
      ...SIGNED_IN,
      'GET /api/settings/nav': { body: NAV },
      'GET /api/settings/preferences': {
        body: {
          ui: { theme: 'system', classic: false },
          list: { density: 'compact', mode: 'list', page_size: 50 },
          reading: {},
          composing: { undo_send_seconds: 10 },
          shortcuts: {},
        },
      },
      'PUT /api/settings/preferences': {
        body: {
          ui: { theme: 'dark', classic: false },
          list: { density: 'compact', mode: 'list', page_size: 50 },
          reading: {},
          composing: { undo_send_seconds: 10 },
          shortcuts: {},
        },
      },
    });
    await page.goto('/settings/preferences/ui');
    await expect(page.getByRole('heading', { name: /Nastavenia/ })).toBeVisible();
    await expect(page.getByText('Klasické zobrazenie')).toBeVisible();
    await shot(page, 'phase1f-W12-preferences');
  });

  test('W12 filters and vacation', async ({ page }) => {
    await mockApi(page, {
      ...SIGNED_IN,
      'GET /api/settings/nav': { body: NAV },
      'GET /api/settings/mailboxes/default/filters': { body: { rules: [], script_name: 'roundcube' } },
      'GET /api/settings/mailboxes/default/vacation': {
        body: { enabled: false, subject: 'Mimo kancelárie: {predmet}', body_sk: 'Som mimo.', days: 7 },
      },
    });
    await page.goto('/settings/filters');
    await expect(page.getByText(/Filtre fungujú na serveri/)).toBeVisible();
    await shot(page, 'phase1f-W12-filters');
    await page.goto('/settings/vacation');
    await expect(page.getByText('Automatická odpoveď')).toBeVisible();
    await shot(page, 'phase1f-W12-vacation');
  });

  test('W4e signature edit dialog', async ({ page }) => {
    const draft = {
      id: 'd-1',
      mailbox_id: 'mb-1',
      mode: 'new',
      identity_id: 'id-1',
      to_addrs: [],
      cc_addrs: [],
      bcc_addrs: [],
      subject: '',
      body_html: '<p></p><div data-sm-signature="1"><p><strong>Jana</strong></p></div>',
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
    await mockApi(page, {
      ...SIGNED_IN,
      'POST /api/mail/mailboxes/default/compose': { body: draft },
      'GET /api/mail/compose/d-1': { body: draft },
      'PATCH /api/mail/compose/d-1': {
        body: { ...draft, signature_html_override: '<p>Upravený podpis</p>' },
      },
      'GET /api/mail/mailboxes/default/identities': {
        body: [
          { id: 'id-1', display_name: 'Jana Testová', email: 'jana@smartsro.sk', organization: null, is_default: true },
        ],
      },
      'GET /api/mail/responses': { body: [] },
    });
    await page.goto('/compose?mailbox=default');
    await expect(page.getByRole('button', { name: 'Odoslať' })).toBeVisible();
    await page.getByRole('button', { name: 'Podpis' }).click();
    await expect(page.getByRole('heading', { name: 'Upraviť podpis pre túto správu' })).toBeVisible();
    await shot(page, 'phase1f-W4e-signature');
  });
});
