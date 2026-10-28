import type { Page, Route } from '@playwright/test';

import { DEFAULT_PREFS, expect, foldersView, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

const SIGNED_IN = { 'GET /api/auth/me': { body: ME }, 'GET /api/auth/persons': { body: ME_PICKER } };

const LIST_PREFS = DEFAULT_PREFS.list;

function inboxList(folderId: string) {
  return {
    mode: 'list' as const,
    total: 2,
    page: 1,
    page_size: 50,
    messages: [
      {
        id: 'm-1',
        thread_id: 't-1',
        folder_id: folderId,
        uid: 1,
        subject: 'Kópia faktúry 2026123',
        from_name: 'Ján Novák',
        from_email: 'novak@abcstav.example',
        preview: 'Dobrý deň, prosím o zaslanie kópie faktúry…',
        received_at: '2026-10-26T07:42:00Z',
        sent_at: '2026-10-26T07:42:00Z',
        size: 1200,
        seen: false,
        flagged: false,
        answered: false,
        has_attachments: true,
        thread_count: 1,
      },
      {
        id: 'm-2',
        thread_id: 't-2',
        folder_id: folderId,
        uid: 2,
        subject: 'Cenová ponuka M10×30 A2',
        from_name: 'Petra Kováčová',
        from_email: 'petra@example.test',
        preview: 'Posielam ponuku na skrutky…',
        received_at: '2026-10-26T06:10:00Z',
        sent_at: '2026-10-26T06:10:00Z',
        size: 800,
        seen: true,
        flagged: false,
        answered: false,
        has_attachments: false,
        thread_count: 1,
      },
    ],
    threads: [] as unknown[],
    prefs: LIST_PREFS,
  };
}

function detail(id = 'm-1') {
  return {
    id,
    thread_id: 't-1',
    folder_id: 'f-1',
    uid: 1,
    message_id: '<1@example.test>',
    subject: 'Kópia faktúry 2026123',
    from_name: 'Ján Novák',
    from_email: 'novak@abcstav.example',
    to: [{ name: null, email: 'pilot@smartmail.test' }],
    cc: [],
    sent_at: '2026-10-26T07:42:00Z',
    received_at: '2026-10-26T07:42:00Z',
    size: 1200,
    seen: true,
    flagged: false,
    answered: false,
    body_text: 'Dobrý deň,\nprosím o zaslanie kópie faktúry 2026123.\n',
    body_html_sanitized:
      '<p>Dobrý deň,</p><p>prosím o zaslanie kópie faktúry 2026123.</p>' +
      // Placeholder + signed same-origin proxy (B6) — never put raw https in src (CSP img-src).
      '<p><img src="about:blank#smartmail-remote" ' +
      'data-remote-src="/api/mail/image-proxy?u=https%3A%2F%2Fcdn.example%2Fremote.png&amp;sig=test" alt="" /></p>',
    attachments: [
      {
        id: 'a-1',
        filename: 'faktura-2026123.pdf',
        content_type: 'application/pdf',
        size: 24576,
        is_inline: false,
        av_status: 'skipped',
      },
    ],
    auth_results: null,
    thread_status: 'open',
    snoozed_until: null,
    assignee_id: null,
    // B6: banner only when the server offers remote images for this sender/mode
    remote_images_offered: true,
    remote_images_mode: 'known' as const,
  };
}

async function mockMail(page: Page, extras: Record<string, { body: unknown; status?: number }> = {}) {
  const view = foldersView();
  const inbox = view.folders.find((f) => f.special_use === 'inbox') ?? view.folders[0];
  if (!inbox) throw new Error('foldersView has no inbox');
  const list = inboxList(inbox.id);
  const d = detail();
  d.folder_id = inbox.id;
  await mockApi(page, {
    ...SIGNED_IN,
    'GET /api/mail/mailboxes/default/folders': { body: view },
    [`GET /api/mail/mailboxes/default/folders/${inbox.id}/messages`]: { body: list },
    'GET /api/mail/mailboxes/default/messages/m-1': { body: d },
    'GET /api/mail/mailboxes/default/messages/m-2': { body: { ...d, id: 'm-2', subject: 'Cenová ponuka M10×30 A2' } },
    'POST /api/mail/mailboxes/default/messages/bulk': { body: { ok: 1 } },
    'PUT /api/mail/prefs': { body: DEFAULT_PREFS },
    ...extras,
  });
  await page.route('**/api/mail/mailboxes/default/messages/m-1/source', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'text/plain; charset=utf-8',
      body:
        'From: Ján Novák <novak@abcstav.example>\r\n' +
        'To: pilot@smartmail.test\r\n' +
        'Subject: Kópia faktúry 2026123\r\n' +
        'Message-ID: <1@example.test>\r\n\r\n' +
        'Dobrý deň,\r\nprosím o zaslanie kópie faktúry 2026123.\r\n',
    });
  });
  return { view, inbox, list };
}

test.describe('W2 list & reading (1d)', () => {
  test('W2 light: list with messages and empty reading pane', async ({ page }) => {
    await mockMail(page);
    await page.goto('/mail/default/inbox');
    await expect(page.getByRole('button', { name: 'Výber' })).toBeVisible();
    await expect(page.getByText('Kópia faktúry 2026123')).toBeVisible();
    await expect(page.getByText('Vyberte správu')).toBeVisible();
    await shot(page, 'phase1d-W2-light');
  });

  test('W2 dark mode', async ({ page }) => {
    await mockMail(page, {
      'GET /api/mail/prefs': {
        body: { ...DEFAULT_PREFS, ui: { ...DEFAULT_PREFS.ui, theme: 'dark' } },
      },
    });
    await page.goto('/mail/default/inbox');
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await expect(page.getByText('Kópia faktúry 2026123')).toBeVisible();
    await shot(page, 'phase1d-W2-dark');
  });

  test('W2 Klasické zobrazenie', async ({ page }) => {
    await mockMail(page, {
      'GET /api/mail/prefs': {
        body: { ...DEFAULT_PREFS, ui: { ...DEFAULT_PREFS.ui, classic: true } },
      },
      // Even with triage categories, classic must hide AI TRIEDENIE.
      'GET /api/mail/mailboxes/default/ai/categories': {
        body: {
          categories: [
            {
              id: 'inquiry',
              label_sk: 'Dopyty',
              description_sk: 'žiadosti o ceny',
              color_token: 'warning',
              count: 3,
            },
          ],
        },
      },
    });
    await page.goto('/mail/default/inbox');
    await expect(page.getByTestId('classic-banner')).toBeVisible();
    await expect(page.getByTestId('ai-triage')).toHaveCount(0);
    await page.getByRole('button', { name: /Jana Testová/ }).click();
    await expect(page.getByRole('menuitem', { name: 'Klasické zobrazenie' })).toBeVisible();
    await shot(page, 'phase1d-W2-classic');
  });

  test('W2c reading pane with attachment and blocked remote image', async ({ page }) => {
    await mockMail(page);
    await page.goto('/mail/default/inbox');
    await page.getByRole('option', { name: /Kópia faktúry 2026123/ }).click();
    await expect(page.getByRole('link', { name: /faktura-2026123\.pdf/ })).toBeVisible();
    await expect(page.getByText('Vzdialené obrázky sú zablokované.')).toBeVisible();
    await shot(page, 'phase1d-W2c-reading');
  });

  test('W2e bulk selection bar', async ({ page }) => {
    await mockMail(page);
    await page.goto('/mail/default/inbox');
    await page.getByRole('button', { name: 'Výber' }).click();
    await page.getByRole('menuitem', { name: 'Aktuálna strana' }).click();
    await expect(page.getByText('Vybraté: 2')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Označiť ako prečítané' })).toBeVisible();
    await shot(page, 'phase1d-W2e-bulk');
  });

  test('W2o Nastavenia zoznamu', async ({ page }) => {
    await mockMail(page);
    await page.goto('/mail/default/inbox');
    await page.getByRole('button', { name: 'Možnosti' }).click();
    await expect(page.getByRole('dialog', { name: 'Nastavenia zoznamu' })).toBeVisible();
    await expect(page.getByText('Hustota')).toBeVisible();
    await shot(page, 'phase1d-W2o-options');
  });

  test('W2m print view', async ({ page }) => {
    await mockMail(page);
    await page.addInitScript(() => {
      window.print = () => undefined;
    });
    await page.goto('/mail/default/inbox/t-1/print?m=m-1');
    await expect(page.getByRole('heading', { name: 'Kópia faktúry 2026123' })).toBeVisible();
    await expect(page.getByText('faktura-2026123.pdf')).toBeVisible();
    await shot(page, 'phase1d-W2m-print');
  });

  test('W2n message source', async ({ page }) => {
    await mockMail(page);
    await page.goto('/mail/default/inbox/t-1/source/m-1');
    await expect(page.getByRole('heading', { name: 'Zdroj správy' })).toBeVisible();
    await expect(page.getByText('Message-ID: <1@example.test>')).toBeVisible();
    await shot(page, 'phase1d-W2n-source');
  });
});
