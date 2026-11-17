import AxeBuilder from '@axe-core/playwright';

import { DEFAULT_PREFS, expect, foldersView, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

/** W2p Hlavičky správy (Figma frame 241:93336 „W2o Hlavičky správy (dialóg)“). Fictional data only. */
const HEADERS = {
  headers: [
    { name: 'Return-Path', value: '<objednavky@fiktivna-firma.example>' },
    {
      name: 'Received',
      value:
        'from mx004.example.net (mx004.example.net [192.0.2.10])\n  by mail.example.net with esmtps (TLS1.3); Tue, 17 Nov 2026 07:41:26 +0100',
    },
    { name: 'From', value: 'Jana Fiktívna <objednavky@fiktivna-firma.example>' },
    { name: 'To', value: 'eshop@smartmail.test' },
    { name: 'Subject', value: 'Rozvoz dnešných objednávok' },
    { name: 'Authentication-Results', value: 'mail.example.net; spf=pass; dkim=pass; dmarc=pass' },
  ],
  auth_results: { spf: 'pass', dkim: 'pass', dmarc: 'pass' },
};

async function open(page: import('@playwright/test').Page) {
  const view = foldersView();
  const inbox = view.folders.find((f) => f.special_use === 'inbox') ?? view.folders[0];
  if (!inbox) throw new Error('no inbox');
  const row = {
    id: 'm-1',
    thread_id: 't-1',
    folder_id: inbox.id,
    uid: 1,
    subject: 'Rozvoz dnešných objednávok',
    from_name: 'Jana Fiktívna',
    from_email: 'objednavky@fiktivna-firma.example',
    preview: 'Dobrý deň…',
    received_at: '2026-11-17T06:41:20Z',
    sent_at: '2026-11-17T06:41:20Z',
    size: 1200,
    seen: true,
    flagged: false,
    answered: false,
    has_attachments: false,
    thread_count: 1,
  };
  await mockApi(page, {
    'GET /api/auth/me': { body: ME },
    'GET /api/auth/persons': { body: ME_PICKER },
    'GET /api/system/info': { body: { admin_contact_email: null, features: {} } },
    'GET /api/mail/mailboxes/default/folders': { body: view },
    [`GET /api/mail/mailboxes/default/folders/${inbox.id}/messages`]: {
      body: { mode: 'list', total: 1, page: 1, page_size: 50, messages: [row], threads: [], prefs: DEFAULT_PREFS.list },
    },
    'GET /api/mail/mailboxes/default/messages/m-1': {
      body: {
        ...row,
        message_id: '<1@example.test>',
        to: [{ name: null, email: 'eshop@smartmail.test' }],
        cc: [],
        body_text: 'Dobrý deň.',
        body_html_sanitized: '<p>Dobrý deň.</p>',
        attachments: [],
        auth_results: HEADERS.auth_results,
        thread_status: 'open',
        snoozed_until: null,
        assignee_id: null,
        remote_images_offered: false,
        remote_images_mode: 'never',
      },
    },
    'GET /api/mail/mailboxes/default/messages/m-1/headers': { body: HEADERS },
    'GET /api/purchasing/mailboxes/default/messages/m-1/documents': { body: [] },
  });
  await page.goto('/mail/default/inbox');
  await page.getByText('Rozvoz dnešných objednávok').first().click();
}

test('W2p Hlavičky správy: all headers, auth summary, Kopírovať, Esc closes @mobile', async ({ page }, info) => {
  await open(page);
  await page.getByTestId('open-headers').click();
  const dialog = page.getByRole('dialog', { name: 'Hlavičky správy' });
  await expect(dialog).toBeVisible();
  const list = dialog.getByTestId('headers-list');
  await expect(list).toContainText('Return-Path: <objednavky@fiktivna-firma.example>');
  await expect(list).toContainText('by mail.example.net with esmtps');
  await expect(dialog).toContainText('Technické údaje o doručení správy. Overenie odosielateľa: SPF, DKIM, DMARC ✓');
  if (info.project.name === 'desktop') {
    const axe = await new AxeBuilder({ page })
      .include('[data-testid="headers-dialog"]')
      .withTags(['wcag2a', 'wcag2aa'])
      .analyze();
    expect(axe.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')).toEqual([]);
  }
  await shot(page, `w2p-headers-${info.project.name}`);
  if (info.project.name === 'desktop') {
    await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
    await dialog.getByRole('button', { name: 'Kopírovať' }).click();
    await expect(page.getByText('Hlavičky sú skopírované.')).toBeVisible();
    const copied = await page.evaluate(() => navigator.clipboard.readText());
    expect(copied.split('\n')[0]).toBe('Return-Path: <objednavky@fiktivna-firma.example>');
  }
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
});

test('W2p Zobraziť zdroj opens W2n in a new tab', async ({ page, context }) => {
  await open(page);
  await page.getByTestId('open-headers').click();
  const popup = context.waitForEvent('page');
  await page.getByRole('button', { name: 'Zobraziť zdroj' }).click();
  await expect(await popup).toHaveURL(/\/source\/m-1$/);
});
