import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import type { Page } from '@playwright/test';

import { DEFAULT_PREFS, expect, foldersView, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

/** Issue #46: W2l attachment preview (pdf.js, images) instead of an immediate download. Fictional files. */
const SIGNED_IN = { 'GET /api/auth/me': { body: ME }, 'GET /api/auth/persons': { body: ME_PICKER } };
const PDF = readFileSync(fileURLToPath(new URL('./assets/preview-2pages.pdf', import.meta.url)));
const PNG = readFileSync(fileURLToPath(new URL('./assets/preview-image.png', import.meta.url)));
const ISDOC =
  '<?xml version="1.0"?><Invoice xmlns="http://isdoc.cz/namespace/2013"><ID>2611452</ID>' +
  '<IssueDate>2026-10-20</IssueDate><LegalMonetaryTotal><PayableAmount>373.20</PayableAmount></LegalMonetaryTotal>' +
  '<script>alert(1)</script></Invoice>';

const att = (id: string, filename: string, content_type: string, av_status = 'clean') => ({
  id,
  filename,
  content_type,
  size: 412_000,
  is_inline: false,
  av_status,
});
const ATTACHMENTS = [
  att('a-pdf', 'Faktura_2611452.pdf', 'application/pdf'),
  att('a-png', 'fotka-tovaru.png', 'image/png'),
  att('a-xml', 'Faktura_2611452.isdoc', 'application/octet-stream'),
  att('a-zip', 'podklady.zip', 'application/zip'),
  att('a-bad', 'virus.pdf', 'application/pdf', 'infected'),
];

async function mockMail(page: Page) {
  const view = foldersView();
  const inbox = view.folders.find((f) => f.special_use === 'inbox') ?? view.folders[0];
  if (!inbox) throw new Error('foldersView has no inbox');
  const row = {
    id: 'm-1',
    thread_id: 't-1',
    folder_id: inbox.id,
    uid: 1,
    subject: 'Faktura 2611452',
    from_name: 'Fixtech CZ fakturace',
    from_email: 'fakturacia@fixtech.example',
    preview: 'v příloze zasíláme fakturu',
    received_at: '2026-10-26T07:42:00Z',
    sent_at: '2026-10-26T07:42:00Z',
    size: 1200,
    seen: true,
    flagged: false,
    answered: false,
    has_attachments: true,
    thread_count: 1,
  };
  await mockApi(page, {
    ...SIGNED_IN,
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
        body_text: 'Dobrý den, v příloze zasíláme fakturu.',
        body_html_sanitized: '<p>Dobrý den, v příloze zasíláme fakturu.</p>',
        attachments: ATTACHMENTS,
        auth_results: null,
        thread_status: 'open',
        snoozed_until: null,
        assignee_id: null,
        remote_images_offered: false,
        remote_images_mode: 'known',
      },
    },
  });
  const files: Record<string, { body: Buffer | string; contentType: string } | null> = {
    'a-pdf': { body: PDF, contentType: 'application/pdf' },
    'a-png': { body: PNG, contentType: 'image/png' },
    'a-xml': { body: ISDOC, contentType: 'application/octet-stream' },
    'a-zip': { body: 'PK', contentType: 'application/zip' },
    'a-bad': null,
  };
  const fetched: string[] = [];
  await page.route('**/api/mail/mailboxes/default/attachments/*', async (route) => {
    const id = new URL(route.request().url()).pathname.split('/').pop() ?? '';
    fetched.push(id);
    const file = files[id];
    if (!file) return route.fulfill({ status: 403, json: { detail: { code: 'attachment_infected' } } });
    await route.fulfill({
      body: file.body,
      contentType: file.contentType,
      headers: { 'Content-Disposition': `attachment; filename="${id}"` },
    });
  });
  return { fetched };
}

async function openMessage(page: Page) {
  await page.goto('/mail/default/inbox');
  await page.getByText('Faktura 2611452').first().click();
  await expect(page.getByRole('link', { name: /Faktura_2611452\.pdf/ })).toBeVisible();
}

test('#46 W2l PDF: page 1 rendered, next page, zoom, Esc closes @mobile', async ({ page }, info) => {
  await mockMail(page);
  await openMessage(page);
  await page.getByRole('link', { name: /Faktura_2611452\.pdf/ }).click();

  const box = page.getByTestId('attachment-lightbox');
  await expect(box).toBeVisible();
  await expect(box.getByTestId('pdf-page')).toHaveText('Strana 1 / 2');
  await expect(box.getByTestId('pdf-page-view')).toHaveAttribute('data-rendered', '1');
  // the text layer is real, selectable text (pdf.js), not an embedded PDF
  await expect(box.getByText('FAKTURA 2611452 (fiktivna)')).toBeAttached();
  await expect(page.locator('embed, iframe, object')).toHaveCount(0);
  await shot(page, `issue46-W2l-pdf-${info.project.name}`);

  await box.getByRole('button', { name: 'Ďalšia strana' }).click();
  await expect(box.getByTestId('pdf-page')).toHaveText('Strana 2 / 2');
  await expect(box.getByTestId('pdf-page-view')).toHaveAttribute('data-rendered', '2');
  await expect(box.getByText('Celkem: 373,20 EUR')).toBeAttached();

  const canvas = box.locator('canvas');
  const before = (await canvas.boundingBox())?.width ?? 0;
  await box.getByRole('button', { name: 'Zväčšiť' }).click();
  await expect.poll(async () => (await canvas.boundingBox())?.width ?? 0).toBeGreaterThan(before);

  await page.keyboard.press('Escape');
  await expect(box).toHaveCount(0);
});

test('#46 W2l image, ISDOC table and ←/→ between attachments @mobile', async ({ page }, info) => {
  await mockMail(page);
  await openMessage(page);
  await page.getByRole('link', { name: /fotka-tovaru\.png/ }).click();
  const box = page.getByTestId('attachment-lightbox');
  await expect(box.getByRole('img', { name: 'fotka-tovaru.png' })).toBeVisible();
  await box.getByRole('button', { name: 'Otočiť' }).click();
  await expect(box.getByRole('img', { name: 'fotka-tovaru.png' })).toHaveAttribute('style', /rotate\(90deg\)/);
  await shot(page, `issue46-W2l-image-${info.project.name}`);

  await page.keyboard.press('ArrowRight');
  const table = box.getByTestId('xml-table');
  await expect(table).toContainText('PayableAmount');
  await expect(table).toContainText('373.20');
  await page.keyboard.press('ArrowLeft');
  await page.keyboard.press('ArrowLeft');
  await expect(box.getByTestId('pdf-page')).toHaveText('Strana 1 / 2');
});

test('#46 other types download; infected files never open', async ({ page }) => {
  const { fetched } = await mockMail(page);
  await openMessage(page);
  const download = page.waitForEvent('download');
  await page.getByRole('link', { name: /podklady\.zip/ }).click();
  expect((await download).suggestedFilename()).toBe('podklady.zip');
  await expect(page.getByTestId('attachment-lightbox')).toHaveCount(0);

  await page.getByRole('link', { name: /virus\.pdf/ }).click();
  await expect(page.getByTestId('attachment-lightbox')).toHaveCount(0);
  expect(fetched).not.toContain('a-bad');
});

test('#46 Tlačiť prints the rendered pages, never the PDF itself', async ({ page }) => {
  await page.addInitScript(() => {
    (window as unknown as { printed: number }).printed = 0;
    window.print = () => {
      const images = document.querySelectorAll('body.printing-pages > .print-pages img').length;
      (window as unknown as { printed: number }).printed = images;
    };
  });
  await mockMail(page);
  await openMessage(page);
  await page.getByRole('link', { name: /Faktura_2611452\.pdf/ }).click();
  const box = page.getByTestId('attachment-lightbox');
  await expect(box.getByTestId('pdf-page-view')).toHaveAttribute('data-rendered', '1');
  await box.getByRole('button', { name: 'Tlačiť' }).click();
  await expect.poll(() => page.evaluate(() => (window as unknown as { printed: number }).printed)).toBe(2);
});
