import AxeBuilder from '@axe-core/playwright';

import { DEFAULT_PREFS, expect, foldersView, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

/** #208 AI card „Príjem tovaru“ in the thread (Figma 22:6603). Read-only, no Money write. Fictional data only. */
const WAREHOUSE = { ...ME, person: { ...ME.person, role: 'warehouse' } };
const card = (extra: Record<string, unknown> = {}) => ({
  id: 'd-1',
  status: 'needs_review',
  kind: 'invoice',
  filename: 'Faktura_2611452.pdf',
  attachment_id: 'a-1',
  supplier_name: 'Fiktívny dodávateľ s.r.o.',
  supplier_ico: '27654321',
  supplier_in_money: true,
  doc_number: '2611452',
  currency: 'EUR',
  total: '373.20',
  lines: 8,
  matched: 7,
  to_confirm: 1,
  unmatched: 0,
  matching_done: true,
  confidence: 0.96,
  checks: [],
  money_number: null,
  error: null,
  money_available: true,
  ...extra,
});

async function open(page: import('@playwright/test').Page, docs: () => unknown) {
  const view = foldersView();
  const inbox = view.folders.find((f) => f.special_use === 'inbox') ?? view.folders[0];
  if (!inbox) throw new Error('no inbox');
  const row = {
    id: 'm-1',
    thread_id: 't-1',
    folder_id: inbox.id,
    uid: 1,
    subject: 'Faktura 2611452',
    from_name: 'Fiktívny dodávateľ fakturace',
    from_email: 'fakturacia@dodavatel.example',
    preview: 'V příloze zasíláme fakturu…',
    received_at: '2026-11-03T08:50:00Z',
    sent_at: '2026-11-03T08:50:00Z',
    size: 1200,
    seen: true,
    flagged: false,
    answered: false,
    has_attachments: true,
    thread_count: 1,
  };
  await mockApi(page, {
    'GET /api/auth/me': { body: WAREHOUSE },
    'GET /api/auth/persons': { body: { ...ME_PICKER, persons: [WAREHOUSE.person] } },
    'GET /api/system/info': { body: { admin_contact_email: null, features: { money: true } } },
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
        body_text: 'Dobrý den, v příloze zasíláme fakturu č. 2611452.',
        body_html_sanitized: '<p>Dobrý den, v příloze zasíláme fakturu č. 2611452.</p>',
        attachments: [
          {
            id: 'a-1',
            filename: 'Faktura_2611452.pdf',
            content_type: 'application/pdf',
            size: 86_016,
            is_inline: false,
            av_status: 'clean',
          },
        ],
        auth_results: null,
        thread_status: 'open',
        snoozed_until: null,
        assignee_id: null,
        remote_images_offered: false,
        remote_images_mode: 'never',
      },
    },
    'GET /api/money/messages/m-1/customer': {
      body: {
        email: 'fakturacia@dodavatel.example',
        method: 'none',
        confidence: 0,
        needs_confirmation: false,
        company: null,
        candidates: [],
      },
    },
    'GET /api/purchasing/mailboxes/default/messages/m-1/documents': () => ({ body: docs() }),
    'POST /api/purchasing/documents/d-1/ignore': { body: card({ status: 'ignored' }) },
    'GET /api/purchasing/documents/d-1': { status: 404, body: { detail: { code: 'document_not_found' } } },
  });
  await page.goto('/mail/default/inbox');
  await page.getByText('Faktura 2611452').first().click();
}

test('#208 W2c / M3: Príjem tovaru card with counts → Pripraviť dodací list opens W6h @mobile', async ({
  page,
}, info) => {
  await open(page, () => [card()]);
  const c = page.getByTestId('goods-receipt-card');
  await expect(c).toContainText('Príjem tovaru');
  await expect(c).toContainText('istota 0,96');
  await expect(c).toContainText('Fiktívny dodávateľ s.r.o. · FA 2611452 · 8 položiek');
  await expect(c).toContainText('Dodávateľ v Money (IČO 27654321 sedí)');
  await expect(c).toContainText('Spárované 7 / 8 – 1 na potvrdenie');
  await expect(c).toContainText('Súčet sedí s dokladom (373,20 €)');
  await expect(c.getByTestId('goods-progress')).toHaveAttribute(
    'aria-label',
    '7 spárovaných, 1 na potvrdenie, 0 nespárovaných',
  );
  await expect(c).toContainText('Návrh AI – nič sa neodošle ani nezapíše bez vášho schválenia.');
  if (info.project.name === 'desktop') {
    const axe = await new AxeBuilder({ page })
      .include('[data-testid="goods-receipt-card"]')
      .withTags(['wcag2a', 'wcag2aa'])
      .analyze();
    expect(axe.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')).toEqual([]);
  }
  await shot(page, `issue208-W2c-${info.project.name}`);
  await c.getByTestId('goods-open').click();
  await expect(page).toHaveURL(/\/docs\/delivery-notes\/d-1$/);
});

test('#208 Zamietnuť hides the card; extracting and Money offline states', async ({ page }) => {
  let docs: unknown[] = [card()];
  await open(page, () => docs);
  const c = page.getByTestId('goods-receipt-card');
  await c.getByTestId('goods-reject').click();
  docs = [];
  await page
    .getByRole('dialog', { name: 'Zamietnuť návrh príjmu?' })
    .getByRole('button', { name: 'Zamietnuť' })
    .click();
  await expect(page.getByTestId('goods-receipt-card')).toHaveCount(0);
});

test('#208 card while AI reads the document and with Money offline', async ({ page }) => {
  let docs: unknown[] = [card({ status: 'extracting', lines: 0, matching_done: false, total: null })];
  await open(page, () => docs);
  await expect(page.getByTestId('goods-reading')).toContainText('AI číta doklad…');
  await expect(page.getByTestId('goods-open')).toBeDisabled();
  docs = [card({ supplier_in_money: null, money_available: false, matching_done: false, matched: 0, to_confirm: 0 })];
  // the card refreshes on its own while the document is being read
  await expect(page.getByTestId('goods-receipt-card')).toContainText('Money nedostupné', { timeout: 10_000 });
  await expect(page.getByTestId('goods-progress')).toHaveCount(0);
});
