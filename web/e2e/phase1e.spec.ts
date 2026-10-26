import { DEFAULT_PREFS, expect, foldersView, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

const SIGNED_IN = { 'GET /api/auth/me': { body: ME }, 'GET /api/auth/persons': { body: ME_PICKER } };

const SENDERS = [
  'Ján Novák',
  'Petra Kováčová',
  'Klaus Weber',
  'Lucia Beňová',
  'Martin Kráľ',
  'Eva Malá',
  'Kuriér Express',
  'Fakturácia Fixtech',
];

const SUBJECTS = [
  'Kópia faktúry 20261234',
  'Cenová ponuka M10×30 A2 – urgentné',
  'Prosím o zaslanie aktuálneho cenníka skrutiek DIN 933 M6–M16 vrátane dodacích lehôt a množstevných zliav 20267890',
  'Objednávka PO-20264567',
  'Reklamácia – podložky M12 a nesprávny materiál A2 namiesto A4',
  'Dodacia lehota – kotvy chemické',
  'Dopyt: skrutky DIN 933 M8×25 A2',
  'Vlákno dodávky DL-seed-1 – potvrdenie množstva a termínu',
  'Re: Vlákno dodávky DL-seed-1 – potvrdenie množstva a termínu',
  'Otázka k dodávke 20261111',
];

/** ≥ 60 fictional rows so W2 screenshots look like normal Roundcube use (Phase 1e). */
function richInboxList(folderId: string, total = 64) {
  const messages = Array.from({ length: total }, (_, i) => ({
    id: `m-${i + 1}`,
    thread_id: i % 9 === 7 ? `t-thread-${Math.floor(i / 9)}` : `t-${i + 1}`,
    folder_id: folderId,
    uid: i + 1,
    subject: SUBJECTS[i % SUBJECTS.length],
    from_name: SENDERS[i % SENDERS.length],
    from_email: `sender${i % 8}@example.test`,
    preview: 'Dobrý deň, fiktívna správa pre screenshot…',
    received_at: new Date(Date.UTC(2026, 9, 26, 16, 0) - i * 3600_000).toISOString(),
    sent_at: new Date(Date.UTC(2026, 9, 26, 16, 0) - i * 3600_000).toISOString(),
    size: 1200 + i * 10,
    seen: i % 4 !== 0,
    flagged: i % 11 === 0,
    answered: i % 9 === 8,
    has_attachments: i % 5 === 0,
    thread_count: i % 9 === 7 || i % 9 === 8 ? 2 : 1,
  }));
  return {
    mode: 'list' as const,
    total,
    page: 1,
    page_size: 50,
    messages: messages.slice(0, 50),
    threads: [] as unknown[],
    prefs: { ...DEFAULT_PREFS.list, page_size: 50 },
  };
}

test.describe('Phase 1e — W2 full mailbox + compose', () => {
  test('W2 light with 60+ fictional messages (long subjects, attachments, unread)', async ({ page }) => {
    const view = foldersView();
    const inbox = view.folders.find((f) => f.special_use === 'inbox') ?? view.folders[0];
    if (!inbox) throw new Error('no inbox');
    inbox.total = 64;
    inbox.unread = 16;
    const list = richInboxList(inbox.id, 64);
    await mockApi(page, {
      ...SIGNED_IN,
      'GET /api/mail/mailboxes/default/folders': { body: view },
      [`GET /api/mail/mailboxes/default/folders/${inbox.id}/messages`]: { body: list },
    });
    await page.goto('/mail/default/inbox');
    await expect(page.getByText('Kópia faktúry 20261234').first()).toBeVisible();
    await expect(page.getByText(/cenníka skrutiek DIN 933/).first()).toBeVisible();
    await shot(page, 'phase1e-W2-full-mailbox-light');
  });

  test('W2 dark full mailbox', async ({ page }) => {
    const view = foldersView();
    const inbox = view.folders.find((f) => f.special_use === 'inbox') ?? view.folders[0];
    if (!inbox) throw new Error('no inbox');
    inbox.total = 64;
    inbox.unread = 16;
    await mockApi(page, {
      ...SIGNED_IN,
      'GET /api/mail/prefs': { body: { ...DEFAULT_PREFS, ui: { ...DEFAULT_PREFS.ui, theme: 'dark' } } },
      'GET /api/mail/mailboxes/default/folders': { body: view },
      [`GET /api/mail/mailboxes/default/folders/${inbox.id}/messages`]: { body: richInboxList(inbox.id) },
    });
    await page.goto('/mail/default/inbox');
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await shot(page, 'phase1e-W2-full-mailbox-dark');
  });

  test('W4 compose new message', async ({ page }) => {
    const draft = {
      id: 'd-1',
      mailbox_id: 'mb-1',
      mode: 'new',
      identity_id: 'id-1',
      to_addrs: [],
      cc_addrs: [],
      bcc_addrs: [],
      subject: '',
      body_html: '<p></p><div data-sm-signature="1"><p><strong>Jana Testová</strong></p></div>',
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
      'PATCH /api/mail/compose/d-1': { body: draft },
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
    });
    await page.goto('/compose?mailbox=default');
    await expect(page.getByRole('button', { name: 'Odoslať' })).toBeVisible();
    await expect(page.getByText('Odpovedá: Jana Testová')).toBeVisible();
    await shot(page, 'phase1e-W4-compose');
  });
});
