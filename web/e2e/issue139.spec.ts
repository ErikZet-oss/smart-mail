import type { Page } from '@playwright/test';

import { DEFAULT_PREFS, expect, foldersView, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

// #139 W3 Viac › „Vystaviť prehlásenie o zhode…“ → dialog → preview → issue (no Figma frame: Dialog + table).

const SIGNED_IN = { 'GET /api/auth/me': { body: ME }, 'GET /api/auth/persons': { body: ME_PICKER } };

const row = (id: string, folderId: string, subject: string) => ({
  id,
  thread_id: `t-${id}`,
  folder_id: folderId,
  uid: Number(id.slice(1)),
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

const SUBJECTS: Record<string, string> = {
  m1: 'Kópia faktúry 2026123',
  m2: 'Cenová ponuka M10×30 A2',
  m3: 'Reklamácia',
};

async function setup(page: Page, extra: Parameters<typeof mockApi>[1] = {}) {
  const view = foldersView();
  const inbox = view.folders.find((f) => f.special_use === 'inbox') ?? view.folders[0];
  if (!inbox) throw new Error('foldersView has no inbox');
  const gone = new Set<string>();
  const bulkCalls: { action: string; message_ids: string[] }[] = [];
  const detail = (id: string) => ({
    ...row(id, inbox.id, SUBJECTS[id] ?? id),
    message_id: `<${id}@example.test>`,
    to: [{ name: null, email: 'pilot@smartmail.test' }],
    cc: [],
    body_text: `Text ${id}`,
    body_html_sanitized: `<p>Text ${id}</p>`,
    attachments: [],
    auth_results: null,
    thread_status: 'open',
    snoozed_until: null,
    assignee_id: null,
    remote_images_offered: false,
    remote_images_mode: 'known',
  });
  await mockApi(page, {
    ...SIGNED_IN,
    'GET /api/mail/mailboxes/default/folders': { body: view },
    [`GET /api/mail/mailboxes/default/folders/${inbox.id}/messages`]: () => {
      const messages = Object.keys(SUBJECTS)
        .filter((id) => !gone.has(id))
        .map((id) => row(id, inbox.id, SUBJECTS[id] ?? id));
      return {
        body: {
          mode: 'list',
          total: messages.length,
          page: 1,
          page_size: 50,
          messages,
          threads: [],
          prefs: DEFAULT_PREFS.list,
        },
      };
    },
    'GET /api/mail/mailboxes/default/messages/m1': { body: detail('m1') },
    'GET /api/mail/mailboxes/default/messages/m2': { body: detail('m2') },
    'GET /api/mail/mailboxes/default/messages/m3': { body: detail('m3') },
    'POST /api/mail/mailboxes/default/messages/bulk': (payload) => {
      const body = payload as { action: string; message_ids: string[] };
      bulkCalls.push(body);
      if (body.action === 'delete' || body.action === 'purge') body.message_ids.forEach((id) => gone.add(id));
      return { body: { ok: body.message_ids.length } };
    },
    'PUT /api/mail/prefs': { body: DEFAULT_PREFS },
    ...extra,
  });
  return { bulkCalls };
}

const option = (page: Page, subject: string) => page.getByRole('option').filter({ hasText: subject });

test('#139 issue a declaration from a mail; blocked without a branch stamp', async ({ page }, info) => {
  const issued: unknown[] = [];
  let stamp = false;
  await setup(page, {
    'POST /api/documents/conformity/preview': { body: {} },
    'POST /api/documents/conformity': (payload) => {
      if (!stamp) return { status: 409, body: { detail: { code: 'no_branch_stamp' } } };
      issued.push(payload);
      return {
        status: 201,
        body: {
          id: 'pz1',
          number: 'PZ-2026-0007',
          issued_on: '2026-10-30',
          branch_id: 'b1',
          signer: 'Ján Vedúci',
          items: 2,
          sha256: 'x',
          draft_id: null,
        },
      };
    },
  });
  await page.goto('/mail/default/inbox');
  await option(page, 'Reklamácia').click();
  await expect(page.getByText('Text m3')).toBeVisible();
  await page.getByRole('button', { name: 'Viac' }).first().click();
  await page.getByRole('menuitem', { name: 'Vystaviť prehlásenie o zhode…' }).click();
  const dialog = page.getByRole('dialog', { name: 'Prehlásenie o zhode (atest 2.1)' });
  await expect(dialog.getByLabel('Odberateľ')).toHaveValue('Ján Novák, novak@abcstav.example');
  await dialog.getByLabel('Doklad / zákazka').fill('FA 2026/0815');
  await dialog.getByLabel('Názov výrobku 1').fill('Matica M8 Zn');
  await dialog.getByLabel('Norma 1').fill('DIN 934');
  await dialog.getByRole('button', { name: 'Pridať riadok' }).click();
  await dialog.getByLabel('Názov výrobku 2').fill('Podložka 8,4 Zn');
  await shot(page, `issue139-dialog-${info.project.name}`);

  await dialog.getByRole('button', { name: 'Vystaviť' }).click();
  await expect(dialog.getByRole('alert')).toContainText('Pobočka nemá nahratú pečiatku');
  stamp = true;
  await dialog.getByRole('button', { name: 'Vystaviť' }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText('Prehlásenie PZ-2026-0007 je vystavené.')).toBeVisible();
  expect(issued[0]).toMatchObject({
    customer: 'Ján Novák, novak@abcstav.example',
    document_ref: 'FA 2026/0815',
    message_id: 'm3',
    items: [
      { nazov: 'Matica M8 Zn', kod: '', norma: 'DIN 934', poznamka: '' },
      { nazov: 'Podložka 8,4 Zn', kod: '', norma: '', poznamka: '' },
    ],
  });
});

test('#139 C AI card opens the prefilled dialog; issuing sends the suggestion id', async ({ page }) => {
  const issued: unknown[] = [];
  await setup(page, {
    'GET /api/mail/mailboxes/default/messages/m3/suggestions': {
      body: [
        {
          id: 's-pz',
          type: 'conformity_declaration',
          status: 'pending',
          to: [],
          subject: '',
          body: '',
          language: 'sk',
          rationale: 'Zákazník žiada atest 2.1.',
          confidence: 0.8,
          checks: [],
          blocked: false,
          conformity: {
            customer: 'ABC Stav s.r.o., Hlavná 1, 949 01 Nitra',
            document_ref: 'FV2026/0815',
            items: [{ nazov: 'Skrutka M8x40', kod: '', norma: 'DIN 933', poznamka: '' }],
          },
        },
      ],
    },
    'POST /api/documents/conformity': (payload) => {
      issued.push(payload);
      return {
        status: 201,
        body: {
          id: 'pz2',
          number: 'PZ-2026-0008',
          issued_on: '2026-10-30',
          branch_id: 'b1',
          signer: 'Ján Vedúci',
          items: 1,
          sha256: 'x',
          draft_id: null,
        },
      };
    },
  });
  await page.goto('/mail/default/inbox');
  await option(page, 'Reklamácia').click();
  const card = page.getByTestId('ai-conformity-card');
  await expect(card).toContainText('FV2026/0815');
  await expect(card).toContainText('Skrutka M8x40');
  await card.getByRole('button', { name: 'Pripraviť prehlásenie…' }).click();
  const dialog = page.getByRole('dialog', { name: 'Prehlásenie o zhode (atest 2.1)' });
  await expect(dialog.getByLabel('Doklad / zákazka')).toHaveValue('FV2026/0815');
  await expect(dialog.getByLabel('Norma 1')).toHaveValue('DIN 933');
  await dialog.getByRole('button', { name: 'Vystaviť' }).click();
  await expect(page.getByText('Prehlásenie PZ-2026-0008 je vystavené.')).toBeVisible();
  expect(issued[0]).toMatchObject({ suggestion_id: 's-pz', message_id: 'm3', document_ref: 'FV2026/0815' });
});
