import type { Page } from '@playwright/test';

import { expect, mockApi, shot, test } from './fixtures';

/** Issue #65: the „Odpovedá“ chip shows the draft's signature person; after a person switch a hint offers to change
 * the signature; the server swaps only the signature block. Fictional branch Nitra. */
const erik = {
  id: 'p-erik',
  first_name: 'Erik',
  last_name: 'Testový',
  full_name: 'Erik Testový',
  role: 'sales',
  function: 'obchod',
  is_manager: false,
};
const jan = { ...erik, id: 'p-jan', first_name: 'Ján', full_name: 'Ján Testový', function: 'sklad' };
const me = (person: typeof erik) => ({
  account_id: 'a-nitra',
  email: 'nitra@smartmail.test',
  kind: 'branch',
  branch: 'Nitra',
  person,
  needs_person: false,
  read_only: false,
});
const PICKER = {
  branch: 'Nitra',
  email: 'nitra@smartmail.test',
  persons: [erik, jan],
  current_person_id: jan.id,
  last_person_id: jan.id,
  idle_ask_minutes: null,
};
const signature = (name: string) => `<div data-sm-signature="1"><p>${name} – Nitra</p></div>`;
const draft = (person: typeof erik) => ({
  id: 'd-65',
  mailbox_id: 'mb-1',
  mode: 'new',
  identity_id: 'id-1',
  to_addrs: [{ name: 'Peter Hudec', email: 'peter@kovo.example' }],
  cc_addrs: [],
  bcc_addrs: [],
  subject: 'Potvrdenie objednávky',
  body_html: `<p>Dobrý deň, potvrdzujeme.</p>${signature(person.full_name)}`,
  body_text: 'Dobrý deň, potvrdzujeme.',
  include_signature: true,
  signature_html_override: null,
  signature_person_id: person.id,
  signature_person_name: person.full_name,
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
  updated_at: '2026-10-29T10:00:00Z',
});

/** The active person is Ján; the open draft was started by Erik and carries his signature. */
async function openErikDraftAsJan(page: Page) {
  const patches: Record<string, unknown>[] = [];
  await mockApi(page, {
    'GET /api/auth/me': { body: me(jan) },
    'GET /api/auth/persons': { body: PICKER },
    'GET /api/mail/compose/d-65': { body: draft(erik) },
    'PATCH /api/mail/compose/d-65': (body) => {
      patches.push(body as Record<string, unknown>);
      const to = (body as { signature_person_id?: string }).signature_person_id === erik.id ? erik : jan;
      return { body: draft(to) };
    },
    'GET /api/mail/mailboxes/default/identities': {
      body: [
        { id: 'id-1', display_name: 'Nitra', email: 'nitra@smartmail.test', organization: 'Smart', is_default: true },
      ],
    },
    'GET /api/mail/responses': { body: [] },
  });
  await page.goto('/compose/d-65?mailbox=default');
  await expect(page.getByTestId('compose-screen')).toBeVisible();
  return { patches };
}

test('#65 the chip shows the draft person, a person switch offers „zmeniť na …“ @mobile', async ({ page }, info) => {
  const { patches } = await openErikDraftAsJan(page);
  // never: the chip shows one person while the signature belongs to another
  await expect(page.getByTestId('compose-signer')).toContainText('Odpovedá: Erik Testový');
  await expect(page.locator('.compose-editor')).toContainText('Erik Testový – Nitra');
  const hint = page.getByTestId('compose-signer-hint');
  await expect(hint).toContainText('Podpis: Erik Testový – zmeniť na Ján Testový?');
  await shot(page, `issue65-W4-hint-${info.project.name}`);

  await hint.getByRole('button', { name: 'Zmeniť' }).click();
  await expect(page.getByTestId('compose-signer')).toContainText('Odpovedá: Ján Testový');
  await expect(page.locator('.compose-editor')).toContainText('Ján Testový – Nitra');
  await expect(page.locator('.compose-editor')).toContainText('Dobrý deň, potvrdzujeme.');
  await expect(hint).toHaveCount(0);
  expect(patches.at(-1)).toMatchObject({ signature_person_id: jan.id, replace_signature_override: false });
});

test('#65 „Ponechať“ keeps the signature and hides the hint', async ({ page }) => {
  const { patches } = await openErikDraftAsJan(page);
  await page.getByTestId('compose-signer-hint').getByRole('button', { name: 'Ponechať' }).click();
  await expect(page.getByTestId('compose-signer-hint')).toHaveCount(0);
  await expect(page.getByTestId('compose-signer')).toContainText('Odpovedá: Erik Testový');
  expect(patches).toEqual([]);
});

test('#65 the „Odpovedá ▾“ dropdown swaps the signature person @mobile', async ({ page }, info) => {
  const { patches } = await openErikDraftAsJan(page);
  await page.getByTestId('compose-signer').click();
  const menu = page.getByRole('menu', { name: 'Kto podpisuje túto správu' });
  await expect(menu.getByRole('menuitemradio', { name: /Erik Testový/ })).toHaveAttribute('aria-checked', 'true');
  await shot(page, `issue65-W4-menu-${info.project.name}`);
  await menu.getByRole('menuitemradio', { name: /Ján Testový/ }).click();
  await expect(page.getByTestId('compose-signer')).toContainText('Odpovedá: Ján Testový');
  expect(patches.at(-1)).toMatchObject({ signature_person_id: jan.id });
});
