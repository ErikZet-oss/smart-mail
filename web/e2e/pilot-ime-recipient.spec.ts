import { expect, ME, ME_PICKER, mockApi, test } from './fixtures';

const SIGNED_IN = { 'GET /api/auth/me': { body: ME }, 'GET /api/auth/persons': { body: ME_PICKER } };

/**
 * Pilot 2026-11-01 (Android, Samsung keyboard): the address in „Komu“ was still an uncommitted IME composition when
 * „Odoslať“ was tapped. React state was empty → PATCH to_addrs [] → „Chýba príjemca“ although the field showed it.
 * Send must read the fields as they stand in the DOM.
 */
test('send uses the To field as shown even when the input event never fired (IME)', async ({ page }) => {
  const draft = {
    id: 'd-ime',
    mailbox_id: 'mb-1',
    mode: 'forward',
    identity_id: 'id-1',
    to_addrs: [] as { email: string }[],
    cc_addrs: [] as { email: string }[],
    bcc_addrs: [] as { email: string }[],
    subject: 'Fwd: test',
    body_html: '<p>x</p>',
    body_text: 'x',
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
    send_error_meta: null,
    attachments: [],
    checks: [],
    updated_at: '2026-11-01T07:00:00Z',
  };
  const patches: { to_addrs?: { email: string }[] }[] = [];
  await mockApi(page, {
    ...SIGNED_IN,
    'POST /api/mail/mailboxes/default/compose': { body: draft },
    'GET /api/mail/compose/d-ime': { body: draft },
    'PATCH /api/mail/compose/d-ime': (body) => {
      const patch = (body ?? {}) as { to_addrs?: { email: string }[] };
      patches.push(patch);
      return { body: { ...draft, to_addrs: patch.to_addrs ?? [] } };
    },
    'POST /api/mail/compose/d-ime/send': { body: { ...draft, status: 'queued' } },
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
  await expect(page.getByTestId('compose-screen')).toBeVisible();
  const toField = page.getByLabel('Komu');
  await expect(toField).toBeEnabled();
  // Put the text into the DOM without an input event, as an unfinished IME composition leaves it.
  await toField.evaluate((el) => {
    (el as HTMLInputElement).value = 'Nitra@smartsro.sk';
  });
  await page.getByRole('button', { name: 'Odoslať', exact: true }).first().click();

  await expect.poll(() => patches.length).toBeGreaterThan(0);
  expect(patches[patches.length - 1]?.to_addrs).toEqual([{ email: 'Nitra@smartsro.sk' }]);
});

/** Pilot 2026-11-01: the mobile header „Odoslať“ opened W4b with the last saved checks („Chýba príjemca“). */
test('mobile header Odoslať saves the typed recipient first @mobile', async ({ page }, info) => {
  test.skip(info.project.name !== 'mobile', 'mobile header only');
  const stale = [{ code: 'no_recipients', blocking: true, message: 'missing_to' }];
  const draft = {
    id: 'd-hdr',
    mailbox_id: 'mb-1',
    mode: 'forward',
    identity_id: 'id-1',
    to_addrs: [] as { email: string }[],
    cc_addrs: [] as { email: string }[],
    bcc_addrs: [] as { email: string }[],
    subject: 'Fwd: test',
    body_html: '<p>x</p>',
    body_text: 'x',
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
    send_error_meta: null,
    attachments: [],
    checks: stale,
    updated_at: '2026-11-01T07:00:00Z',
  };
  const patches: { to_addrs?: { email: string }[] }[] = [];
  let sent = 0;
  await mockApi(page, {
    ...SIGNED_IN,
    'POST /api/mail/mailboxes/default/compose': { body: draft },
    'GET /api/mail/compose/d-hdr': { body: draft },
    'PATCH /api/mail/compose/d-hdr': (body) => {
      const patch = (body ?? {}) as { to_addrs?: { email: string }[] };
      patches.push(patch);
      const to = patch.to_addrs ?? [];
      return { body: { ...draft, to_addrs: to, checks: to.length ? [] : stale } };
    },
    'POST /api/mail/compose/d-hdr/send': () => {
      sent += 1;
      return { body: { ...draft, to_addrs: [{ email: 'nitra@smartsro.sk' }], checks: [], status: 'queued' } };
    },
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
  await expect(page.getByTestId('compose-screen')).toBeVisible();
  const toField = page.getByLabel('Komu');
  await expect(toField).toBeEnabled();
  await toField.fill('nitra@smartsro.sk');
  await page.locator('header').getByRole('button', { name: 'Odoslať' }).first().click();

  await expect.poll(() => sent).toBe(1);
  expect(patches.some((p) => p.to_addrs?.[0]?.email === 'nitra@smartsro.sk')).toBe(true);
  await expect(page.getByText('Chýba príjemca.')).toHaveCount(0);
});
