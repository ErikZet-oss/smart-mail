import { DEFAULT_PREFS, expect, foldersView, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

const SIGNED_IN = { 'GET /api/auth/me': { body: ME }, 'GET /api/auth/persons': { body: ME_PICKER } };

const AI_CATEGORIES = {
  categories: [
    {
      id: 'inquiry',
      label_sk: 'Dopyty',
      description_sk: 'žiadosti o ceny a dostupnosť',
      color_token: 'warning',
      count: 1,
    },
    {
      id: 'order',
      label_sk: 'Objednávky',
      description_sk: 'objednávky tovaru od zákazníkov',
      color_token: 'success',
      count: 0,
    },
    {
      id: 'invoice_request',
      label_sk: 'Žiadosti o faktúru',
      description_sk: 'prosby o vystavenie alebo kópiu faktúry',
      color_token: 'info',
      count: 0,
    },
    {
      id: 'supplier_document',
      label_sk: 'Doklady dodávateľov',
      description_sk: 'faktúry a dodacie listy od dodávateľov',
      color_token: 'danger',
      count: 0,
    },
    {
      id: 'complaint',
      label_sk: 'Reklamácie',
      description_sk: 'reklamácie tovaru alebo služieb',
      color_token: 'danger',
      count: 0,
    },
    {
      id: 'shipping',
      label_sk: 'Doprava',
      description_sk: 'zásielky, tracking, kuriér',
      color_token: 'info',
      count: 0,
    },
    {
      id: 'payment',
      label_sk: 'Platby',
      description_sk: 'platby, upomienky, potvrdenia úhrad',
      color_token: 'danger',
      count: 0,
    },
    {
      id: 'document_request',
      label_sk: 'Žiadosti o dokument',
      description_sk: 'atesty, certifikáty, technické listy, VOP',
      color_token: 'warning',
      count: 0,
    },
    {
      id: 'supplier_info',
      label_sk: 'Dodávatelia – info',
      description_sk: 'cenníky, výpadky, zmeny cien',
      color_token: 'success',
      count: 0,
    },
    {
      id: 'newsletter',
      label_sk: 'Feed',
      description_sk: 'newslettre a hromadné správy',
      color_token: 'brand',
      count: 0,
    },
  ],
};

const INQUIRY_MSG = {
  id: 'm-inq-1',
  thread_id: 't-inq-1',
  folder_id: 'f-1',
  uid: 11,
  subject: 'Dopyt skrutky M8 DIN 933',
  from_name: 'Ján Novák',
  from_email: 'novak@abcstav.example',
  preview: 'Prosím o cenovú ponuku…',
  received_at: '2026-10-27T08:00:00Z',
  sent_at: '2026-10-27T08:00:00Z',
  size: 900,
  seen: false,
  flagged: false,
  answered: false,
  has_attachments: false,
  thread_count: 1,
  ai_category: 'inquiry',
  ai_priority: 'normal',
  ai_summary: 'Dopyt na skrutky M8 A2 – 500 ks',
  ai_language: 'sk',
  ai_confidence: 0.92,
  ai_note_codes: [] as string[],
};

function mailShell() {
  const view = foldersView();
  view.mailbox.ai_enabled = true;
  view.mailbox.ai_available = true;
  const folderId = view.folders[0]?.id ?? 'f-1';
  return {
    ...SIGNED_IN,
    'GET /api/mail/mailboxes/default/folders': { body: view },
    'POST /api/mail/mailboxes/default/refresh': { body: view },
    'GET /api/mail/prefs': { body: DEFAULT_PREFS },
    'GET /api/mail/mailboxes/default/ai/categories': { body: AI_CATEGORIES },
    [`GET /api/mail/mailboxes/default/folders/${folderId}/messages`]: {
      body: {
        mode: 'list',
        total: 0,
        page: 1,
        page_size: 50,
        messages: [],
        threads: [],
        prefs: DEFAULT_PREFS.list,
      },
    },
    'GET /api/mail/mailboxes/default/ai/views/inquiry/messages': {
      body: {
        category: AI_CATEGORIES.categories[0],
        total: 1,
        page: 1,
        page_size: 50,
        messages: [INQUIRY_MSG],
      },
    },
    'GET /api/mail/mailboxes/default/ai/views/order/messages': {
      body: {
        category: AI_CATEGORIES.categories[1],
        total: 0,
        page: 1,
        page_size: 50,
        messages: [],
      },
    },
    'GET /api/mail/mailboxes/default/messages/m-inq-1': {
      body: {
        ...INQUIRY_MSG,
        message_id: '<inq@example.test>',
        to: [{ name: null, email: 'pilot@smartmail.test' }],
        cc: [],
        body_text: 'Dobrý deň, prosím o cenovú ponuku na skrutky M8.',
        body_html_sanitized: '<p>Dobrý deň, prosím o cenovú ponuku na skrutky M8.</p>',
        attachments: [],
        auth_results: { dmarc: 'pass', spf: 'pass' },
        thread_status: 'open',
        snoozed_until: null,
        assignee_id: null,
        security_notes: [] as string[],
      },
    },
    'GET /api/settings/nav': {
      body: {
        sections: [
          { path: 'preferences', title: 'Nastavenia', admin_only: false },
          { path: 'ai', title: 'AI asistent', admin_only: false },
        ],
        paths: { preferences: '01', ai: '07' },
      },
    },
    'GET /api/settings/preferences': { body: DEFAULT_PREFS },
    'GET /api/settings/profile': {
      body: { first_name: 'Pilot', last_name: 'Test', function: null, phone: null, mobile: null, personal_email: null },
    },
  };
}

test.describe('Phase 2b — W2f AI triage', () => {
  test('W2f Dopyty list with badges and summary', async ({ page }) => {
    await mockApi(page, mailShell());
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/mail/default/view/inquiry');
    await expect(page.getByTestId('ai-triage')).toBeVisible();
    await expect(page.getByTestId('ai-category-list')).toBeVisible();
    await expect(page.getByText('Dopyt skrutky M8 DIN 933')).toBeVisible();
    await expect(page.getByTestId('ai-badge')).toBeVisible();
    await expect(page.getByText('Dopyt na skrutky M8 A2 – 500 ks')).toBeVisible();
    await shot(page, 'phase2b-W2f-dopyty');
    await page.screenshot({
      path: '/opt/cursor/artifacts/screenshots/phase2b-W2f-dopyty-playwright.png',
      fullPage: true,
    });
  });

  test('W2f empty category', async ({ page }) => {
    await mockApi(page, mailShell());
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/mail/default/view/order');
    await expect(page.getByText('Žiadne Objednávky')).toBeVisible();
    await expect(page.getByText('AI ich sem zaradí automaticky.')).toBeVisible();
    await shot(page, 'phase2b-W2f-empty');
    await page.screenshot({
      path: '/opt/cursor/artifacts/screenshots/phase2b-W2f-empty-playwright.png',
      fullPage: true,
    });
  });

  test('classic hides AI triage', async ({ page }) => {
    const handlers = mailShell();
    handlers['GET /api/mail/prefs'] = {
      body: { ...DEFAULT_PREFS, ui: { ...DEFAULT_PREFS.ui, classic: true } },
    };
    await mockApi(page, handlers);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/mail/default/inbox');
    await expect(page.getByTestId('classic-banner')).toBeVisible();
    await expect(page.getByTestId('ai-triage')).toHaveCount(0);
  });

  test('security banner on DMARC fail', async ({ page }) => {
    const handlers = mailShell();
    handlers['GET /api/mail/mailboxes/default/messages/m-inq-1'] = {
      body: {
        ...INQUIRY_MSG,
        message_id: '<inq@example.test>',
        to: [{ name: null, email: 'pilot@smartmail.test' }],
        cc: [],
        body_text: 'Urgent IBAN change',
        body_html_sanitized: '<p>Urgent</p>',
        attachments: [],
        auth_results: { dmarc: 'fail', spf: 'fail' },
        thread_status: 'open',
        snoozed_until: null,
        assignee_id: null,
        security_notes: ['security_dmarc_fail', 'security_display_spoof'],
      },
    };
    await mockApi(page, handlers);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/mail/default/view/inquiry');
    await page.getByText('Dopyt skrutky M8 DIN 933').click();
    await expect(page.getByTestId('security-banners')).toBeVisible();
    await expect(page.getByTestId('security-security_dmarc_fail')).toBeVisible();
  });
});

test.describe('Pilot: open from AI triedenie on mobile', () => {
  test('a message filed into Faktúry opens in its own folder, not a blank screen @mobile', async ({ page }) => {
    const handlers: Parameters<typeof mockApi>[1] = mailShell();
    const invoice = {
      ...INQUIRY_MSG,
      id: 'm-inv-1',
      thread_id: 't-inv-1',
      folder_id: 'f-8', // Faktúry in foldersView(): Sieve filed the supplier invoice there
      subject: 'Faktura E3/2026/00001',
      from_name: 'Fiktívny Dodávateľ',
      from_email: 'fakturacia@dodavatel.example',
      preview: 'Vždy sa riaďte bankovými údajmi na faktúre.',
      ai_category: 'invoice_request',
      ai_summary: 'Faktúra od dodávateľa',
    };
    handlers['GET /api/mail/mailboxes/default/ai/views/invoice_request/messages'] = {
      body: { category: AI_CATEGORIES.categories[2], total: 1, page: 1, page_size: 50, messages: [invoice] },
    };
    // The Faktúry page does not contain the message (older mail, other page): the pane must still open it.
    handlers['GET /api/mail/mailboxes/default/folders/f-8/messages'] = {
      body: {
        mode: 'list',
        total: 0,
        page: 1,
        page_size: 50,
        messages: [],
        threads: [],
        prefs: DEFAULT_PREFS.list,
      },
    };
    handlers['GET /api/mail/mailboxes/default/messages/m-inv-1'] = {
      body: {
        ...invoice,
        message_id: '<inv@example.test>',
        to: [{ name: null, email: 'pilot@smartmail.test' }],
        cc: [],
        body_text: 'Vždy sa riaďte bankovými údajmi na faktúre.',
        body_html_sanitized: '<p>Vždy sa riaďte bankovými údajmi na faktúre.</p>',
        attachments: [],
        auth_results: { dmarc: 'pass', spf: 'pass' },
        thread_status: 'open',
        snoozed_until: null,
        assignee_id: null,
        security_notes: [] as string[],
      },
    };
    await mockApi(page, handlers);
    await page.goto('/mail/default/view/invoice_request');
    await page.getByText('Faktura E3/2026/00001').click();
    await expect(page).toHaveURL(/\/mail\/default\/f-8\/t-inv-1\?m=m-inv-1$/);
    await expect(page.getByTestId('mobile-thread')).toBeVisible();
    await expect(page.getByText('Vždy sa riaďte bankovými údajmi na faktúre.').last()).toBeVisible();
  });
});
