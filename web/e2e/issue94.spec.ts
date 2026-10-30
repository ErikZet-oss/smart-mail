import AxeBuilder from '@axe-core/playwright';
import type { Page } from '@playwright/test';

import { DEFAULT_PREFS, expect, foldersView, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

// #94 Phase 2c: AiSuggestionCard in the reading pane — approve prepares a draft (never sends), reject with chips.

const SIGNED_IN = { 'GET /api/auth/me': { body: ME }, 'GET /api/auth/persons': { body: ME_PICKER } };

const row = (id: string, folderId: string, subject: string) => ({
  id,
  thread_id: `t-${id}`,
  folder_id: folderId,
  uid: 1,
  subject,
  from_name: 'Ján Novák',
  from_email: 'novak@abcstav.example',
  preview: 'Dobrý deň…',
  received_at: '2026-10-26T07:42:00Z',
  sent_at: '2026-10-26T07:42:00Z',
  size: 1200,
  seen: true,
  flagged: false,
  answered: false,
  has_attachments: false,
  thread_count: 1,
});

const CARD: {
  id: string;
  type: string;
  status: string;
  to: string[];
  subject: string;
  body: string;
  language: string;
  rationale: string;
  confidence: number;
  checks: { id: string; level: string; params: Record<string, unknown> }[];
  blocked: boolean;
} = {
  id: 's-1',
  type: 'reply',
  status: 'pending',
  to: ['novak@abcstav.example'],
  subject: 'Re: Kópia faktúry 2026123',
  body: 'Dobrý deň,\n\nkópiu faktúry 2026123 Vám pošleme ešte dnes.\n\nS pozdravom',
  language: 'sk',
  rationale: 'Zákazník žiada kópiu faktúry.',
  confidence: 0.86,
  checks: [{ id: 'new_recipient', level: 'warning', params: { address: 'novak@abcstav.example' } }],
  blocked: false,
};

type Calls = { approve: unknown[]; reject: unknown[] };

async function setup(page: Page, card: typeof CARD = CARD): Promise<Calls> {
  const view = foldersView();
  const inbox = view.folders.find((f) => f.special_use === 'inbox') ?? view.folders[0];
  if (!inbox) throw new Error('foldersView has no inbox');
  const calls: Calls = { approve: [], reject: [] };
  let decided = false;
  await mockApi(page, {
    ...SIGNED_IN,
    'GET /api/mail/mailboxes/default/folders': { body: view },
    [`GET /api/mail/mailboxes/default/folders/${inbox.id}/messages`]: {
      body: {
        mode: 'list',
        total: 1,
        page: 1,
        page_size: 50,
        messages: [row('m1', inbox.id, 'Kópia faktúry 2026123')],
        threads: [],
        prefs: DEFAULT_PREFS.list,
      },
    },
    'GET /api/mail/mailboxes/default/messages/m1': {
      body: {
        ...row('m1', inbox.id, 'Kópia faktúry 2026123'),
        message_id: '<1@example.test>',
        to: [{ name: null, email: 'pilot@smartmail.test' }],
        cc: [],
        body_text: 'Prosím o kópiu faktúry 2026123.',
        body_html_sanitized: '<p>Prosím o kópiu faktúry 2026123.</p>',
        attachments: [],
        auth_results: null,
        thread_status: 'open',
        snoozed_until: null,
        assignee_id: null,
        remote_images_offered: false,
        remote_images_mode: 'known',
        ai_category: 'invoice_request',
      },
    },
    'GET /api/mail/mailboxes/default/messages/m1/suggestions': () => ({ body: decided ? [] : [card] }),
    'POST /api/suggestions/s-1/approve': (payload) => {
      calls.approve.push(payload);
      decided = true;
      return { body: { suggestion_id: 's-1', draft_id: 'd-77', edited: false } };
    },
    'POST /api/suggestions/s-1/reject': (payload) => {
      calls.reject.push(payload);
      decided = true;
      return { body: { status: 'rejected' } };
    },
    'GET /api/compose/d-77': { status: 404, body: { detail: { code: 'draft_not_found' } } },
    'PUT /api/mail/prefs': { body: DEFAULT_PREFS },
  });
  return calls;
}

const card = (page: Page) => page.getByTestId('ai-suggestion-card');
/** #156: the card starts collapsed; approving needs the expanded card. */
const expand = async (page: Page) => {
  await card(page).getByRole('button', { expanded: false }).click();
  await expect(card(page)).toHaveAttribute('data-collapsed', 'false');
};

test.describe('#94 AiSuggestionCard @mobile', () => {
  test('#94 card shows checks, preview and the AI footer; approve opens the draft', async ({ page }, info) => {
    const calls = await setup(page);
    await page.goto('/mail/default/inbox/t-m1');
    await expect(card(page)).toBeVisible();
    await expand(page);
    await expect(card(page)).toHaveAttribute('data-state', 'attention');
    await expect(card(page).getByRole('heading', { name: 'Návrh odpovede' })).toBeVisible();
    await expect(card(page).getByText('Žiadosti o faktúru · slovenčina')).toBeVisible();
    await expect(card(page).getByText('Nový príjemca: novak@abcstav.example')).toBeVisible();
    await expect(card(page).getByText('Bez [[DOPLNIŤ]]')).toBeVisible();
    await expect(card(page).getByText('Návrh AI – nič sa neodošle ani nezapíše bez vášho schválenia.')).toBeVisible();
    await shot(page, `issue94-card-${info.project.name}`);
    const axe = await new AxeBuilder({ page })
      .include('[data-testid="ai-suggestion-card"]')
      .withTags(['wcag2a', 'wcag2aa'])
      .analyze();
    expect(axe.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')).toEqual([]);
    await card(page).getByRole('button', { name: 'Pripraviť koncept' }).click();
    await expect(page).toHaveURL(/\/compose\/d-77/);
    expect(calls.approve).toEqual([{ body: null }]);
  });

  test('#94 edited text is sent with approve', async ({ page }) => {
    const calls = await setup(page);
    await page.goto('/mail/default/inbox/t-m1');
    await expand(page);
    await card(page).getByRole('button', { name: 'Upraviť' }).click();
    await card(page).getByLabel('Text odpovede').fill('Dobrý deň, faktúru 2026123 posielame.');
    await card(page).getByRole('button', { name: 'Pripraviť upravený koncept' }).click();
    await expect(page).toHaveURL(/\/compose\/d-77/);
    expect(calls.approve).toEqual([{ body: 'Dobrý deň, faktúru 2026123 posielame.' }]);
  });

  test('#94 reject with reason chips removes the card', async ({ page }) => {
    const calls = await setup(page);
    await page.goto('/mail/default/inbox/t-m1');
    await card(page).getByRole('button', { name: 'Zamietnuť' }).click();
    await card(page).getByRole('button', { name: 'tón' }).click();
    await card(page).getByRole('button', { name: 'nesprávne údaje' }).click();
    await card(page).getByRole('button', { name: 'Zamietnuť návrh' }).click();
    await expect(page.getByText('Návrh je zamietnutý.')).toBeVisible();
    await expect(card(page)).toHaveCount(0);
    expect(calls.reject).toEqual([{ reasons: ['tone', 'wrong_data'], note: null }]);
  });

  test('#94 blocked card: approve disabled until the text is edited', async ({ page }) => {
    await setup(page, {
      ...CARD,
      body: 'Cena je [[DOPLNIŤ: cena]].',
      checks: [{ id: 'placeholder', level: 'blocking', params: { items: ['[[DOPLNIŤ: cena]]'] } }],
      blocked: true,
    });
    await page.goto('/mail/default/inbox/t-m1');
    await expand(page);
    await expect(card(page)).toHaveAttribute('data-state', 'blocked');
    await expect(card(page).getByRole('button', { name: 'Pripraviť koncept' })).toBeDisabled();
    await card(page).getByRole('button', { name: 'Upraviť' }).click();
    await card(page).getByLabel('Text odpovede').fill('Cena je 0,12 € za kus.');
    await expect(card(page).getByRole('button', { name: 'Pripraviť upravený koncept' })).toBeEnabled();
  });

  test('#156 card is collapsed by default: one line, no approve, reject and expand by keyboard', async ({ page }) => {
    await setup(page);
    await page.goto('/mail/default/inbox/t-m1');
    await expect(card(page)).toHaveAttribute('data-collapsed', 'true');
    await expect(card(page).getByRole('button', { name: 'Pripraviť koncept' })).toHaveCount(0);
    await expect(card(page).getByRole('button', { name: 'Zamietnuť' })).toBeVisible();
    const box = await card(page).boundingBox();
    expect(box?.height ?? 0).toBeLessThanOrEqual(56);
    await card(page).getByRole('button', { expanded: false }).focus();
    await page.keyboard.press('Enter');
    await expect(card(page)).toHaveAttribute('data-collapsed', 'false');
    await expect(card(page).getByRole('button', { name: 'Zbaliť' })).toBeFocused();
    await expect(card(page).getByRole('button', { name: 'Pripraviť koncept' })).toBeVisible();
    await card(page).getByRole('button', { name: 'Zbaliť' }).click();
    await expect(card(page)).toHaveAttribute('data-collapsed', 'true');
  });
});
