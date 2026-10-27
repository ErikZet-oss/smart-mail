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
    { id: '02', path: 'folders', title: 'Priečinky', subs: [] },
    {
      id: '03',
      path: 'identity',
      title: 'Identity',
      subs: [
        { id: '03a', path: 'list', title: 'Identity' },
        { id: '03b', path: 'profile', title: 'Môj profil' },
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
      'GET /api/settings/mailboxes/default/filters': {
        body: {
          script_name: 'roundcube',
          has_backup: true,
          mailbox_scope: 'personal',
          rules: [
            {
              id: 'f1',
              name: 'Dodávatelia Acme',
              enabled: true,
              match: 'anyof',
              editable: true,
              raw: '# rule:[Dodávatelia Acme]\nif address :contains "From" "@acme-parts.test" {\n\tfileinto "Dodávatelia";\n\tstop;\n}\n',
              conditions: [{ field: 'from', op: 'contains', value: '@acme-parts.test' }],
              actions: [
                { type: 'fileinto', value: 'Dodávatelia' },
                { type: 'stop', value: '' },
              ],
            },
            {
              id: 'rc-regex',
              name: 'Regex - len Roundcube',
              enabled: true,
              editable: false,
              readonly_label: 'Pravidlo z Roundcube (len na čítanie)',
              raw: '# rule:[Regex - len Roundcube]\nif header :regex "Subject" "^URGENT-" {\n\tfileinto "INBOX";\n\tstop;\n}\n',
              conditions: [],
              actions: [{ type: 'fileinto', value: 'INBOX' }],
            },
          ],
        },
      },
      'GET /api/settings/mailboxes/default/vacation': {
        body: {
          enabled: false,
          subject: 'Mimo kancelárie: {predmet}',
          body_sk: 'Som mimo.',
          body_en: 'Out of office.',
          body_de: 'Außer Haus.',
          days: 7,
          start: null,
          end: null,
          has_backup: true,
          script_name: 'roundcube',
        },
      },
    });
    await page.goto('/settings/filters');
    await expect(page.getByText(/Filter platí pre celú schránku/)).toBeVisible();
    await expect(page.getByText('Pravidlo z Roundcube (len na čítanie)')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Obnoviť predchádzajúcu verziu' })).toBeVisible();
    await shot(page, 'phase1f-W12-05-filters');
    await page.goto('/settings/vacation');
    await expect(page.getByText('Automatická odpoveď')).toBeVisible();
    await expect(page.getByText('Bez dátumu do platí, kým ju nevypnete.')).toBeVisible();
    await shot(page, 'phase1f-W12-06-vacation');
  });

  test('W12 folders, identity signature source, provider', async ({ page }) => {
    await mockApi(page, {
      ...SIGNED_IN,
      'GET /api/settings/nav': { body: NAV },
      'GET /api/settings/mailboxes/default/identities': {
        body: [
          {
            id: 'id-1',
            display_name: 'Jana Testová',
            email: 'jana@smartsro.sk',
            organization: null,
            is_default: true,
            signature_html: { sk: '<p><strong>Jana Testová</strong><br/>Smart s.r.o.</p>' },
          },
        ],
      },
      'GET /api/settings/mailboxes/default/provider': {
        body: {
          email: 'jana@smartsro.sk',
          imap_host: 'imap-test',
          imap_port: 993,
          provider_admin_url: null,
        },
      },
    });
    await page.goto('/settings/folders');
    await expect(page.getByText(/Priečinky spravujete aj v ľavom stĺpci/)).toBeVisible();
    await shot(page, 'phase1f-W12-02-folders');
    await page.goto('/settings/identity/list');
    await expect(page.getByRole('button', { name: /Jana Testová <jana@smartsro\.sk>/ })).toBeVisible();
    await expect(page.getByRole('button', { name: '<> Zdrojový kód' })).toBeVisible();
    await shot(page, 'phase1f-W12-03a-identity');
    await page.getByRole('button', { name: '<> Zdrojový kód' }).click();
    await expect(page.getByLabel('<> Zdrojový kód')).toHaveValue(/Jana Testová/);
    await shot(page, 'phase1f-W12-03a-identity-source');
    await page.goto('/settings/provider');
    await expect(page.getByText('jana@smartsro.sk')).toBeVisible();
    await expect(page.getByText(/Automatickú odpoveď nastavte v Mimo kancelárie/)).toBeVisible();
    await shot(page, 'phase1f-W12-09b-provider');
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
