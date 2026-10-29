import type { Page } from '@playwright/test';

import { expect, mockApi, shot, test } from './fixtures';

/** Issue #68: the branch login smartsronitra@ sends as nitra@ — the admin sets it in Nastavenia › Identity. Fictional. */
const person = (role: string) => ({
  id: 'p-erik',
  first_name: 'Erik',
  last_name: 'Testový',
  full_name: 'Erik Testový',
  role,
  function: 'vedúci',
  is_manager: true,
});
const me = (role: string) => ({
  account_id: 'a-nitra',
  email: 'smartsronitra@smartsro.sk',
  kind: 'branch',
  branch: 'Nitra',
  person: person(role),
  needs_person: false,
  read_only: false,
});
const IDENTITY = {
  id: 'id-1',
  mailbox_id: 'mb-1',
  display_name: 'Pobočka Nitra',
  email: 'smartsronitra@smartsro.sk',
  organization: 'Smart s.r.o.',
  reply_to: null,
  bcc: [],
  is_default: true,
  signature_html: {},
  signature_images: [],
};

async function open(page: Page, role: string) {
  const saved: Record<string, unknown>[] = [];
  let email = IDENTITY.email;
  await mockApi(page, {
    'GET /api/auth/me': { body: me(role) },
    'GET /api/auth/persons': {
      body: {
        branch: 'Nitra',
        email: 'smartsronitra@smartsro.sk',
        persons: [person(role)],
        current_person_id: 'p-erik',
        last_person_id: 'p-erik',
        idle_ask_minutes: null,
      },
    },
    'GET /api/settings/mailboxes/default/identities': () => ({ body: [{ ...IDENTITY, email }] }),
    'GET /api/settings/mailboxes/default/signature-context': () => ({
      body: {
        mailbox_kind: 'branch',
        account_kind: 'branch',
        branch_managed: true,
        preview_html: `<p>Erik Testový · ${email}</p>`,
        branch_id: 'br-nitra',
      },
    }),
    'PUT /api/settings/identities/id-1': (body) => {
      saved.push(body as Record<string, unknown>);
      email = String((body as { email: string }).email);
      return { body: { ...IDENTITY, ...(body as object) } };
    },
  });
  await page.goto('/settings/identity');
  return { saved };
}

test('#68 W12 admin sets the sender of the branch identity; the preview follows @mobile', async ({ page }, info) => {
  const { saved } = await open(page, 'admin');
  const form = page.getByTestId('branch-identity');
  await expect(form.getByLabel('E-mail')).toHaveValue('smartsronitra@smartsro.sk');
  await form.getByLabel('E-mail').fill('nitra@smartsro.sk');
  await form.getByLabel('Zobrazované meno').fill('Smart s.r.o. – pobočka Nitra');
  await shot(page, `issue68-W12-branch-identity-${info.project.name}`);
  await form.getByRole('button', { name: 'Uložiť' }).click();
  await expect
    .poll(() => saved.at(-1))
    .toMatchObject({
      email: 'nitra@smartsro.sk',
      display_name: 'Smart s.r.o. – pobočka Nitra',
      signature_html: {},
    });
  await expect(page.getByText('Erik Testový · nitra@smartsro.sk')).toBeVisible();
});

test('#68 W12 a non-admin sees the branch sender read-only @mobile', async ({ page }) => {
  await open(page, 'sales');
  const form = page.getByTestId('branch-identity');
  await expect(form.getByLabel('E-mail')).toBeDisabled();
  await expect(form.getByRole('button', { name: 'Uložiť' })).toHaveCount(0);
  await expect(form).toContainText('Odosielateľa pobočkovej schránky mení správca.');
});
