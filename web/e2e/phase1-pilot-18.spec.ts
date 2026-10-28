import { expect, ME, ME_PICKER, mockApi, test } from './fixtures';

const SIGNED_IN = { 'GET /api/auth/me': { body: ME }, 'GET /api/auth/persons': { body: ME_PICKER } };

/** Pilot #18 B2: hung /api/auth/me must show an error screen, not a blank dark page. */
test('B2 F5 with hung /api/auth/me shows Skúsiť znova (not blank)', async ({ page }) => {
  await page.route('**/api/auth/csrf', (route) => route.fulfill({ status: 204, body: '' }));
  await page.route('**/api/auth/me', async (route) => {
    await new Promise((r) => setTimeout(r, 15_000));
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        account_id: 'a1',
        email: 'late@smartmail.test',
        kind: 'personal',
        branch: null,
        person: null,
        needs_person: false,
        read_only: false,
      }),
    });
  });
  // Hang every other API call — a broken `{}` body made ScreenW2 throw before the me-timeout.
  await page.route('**/api/**', async (route) => {
    if (route.request().url().includes('/api/auth/')) return route.fallback();
    await new Promise(() => {
      /* pending until test ends */
    });
  });

  await page.goto('/mail/default/inbox');
  await expect(page.getByTestId('shell-loading')).toBeVisible({ timeout: 3_000 });
  await expect(page.getByTestId('shell-load-error')).toBeVisible({ timeout: 12_000 });
  await expect(page.getByRole('button', { name: 'Skúsiť znova' })).toBeVisible();
  // Must not stay as an empty dark main with only aria-busy
  await expect(page.locator('main[aria-busy="true"]:not([data-testid])')).toHaveCount(0);
});

/** Pilot #18 B7: disallowed recipient must show Slovak error within 2 s (API 422 on Send). */
test('B7 send to disallowed address shows Slovak error within 2s', async ({ page }) => {
  const draft = {
    id: 'd-b7',
    mailbox_id: 'mb-1',
    mode: 'new',
    identity_id: 'id-1',
    to_addrs: [] as { email: string }[],
    cc_addrs: [] as { email: string }[],
    bcc_addrs: [] as { email: string }[],
    subject: '',
    body_html: '<p></p>',
    body_text: '',
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
    updated_at: '2026-10-28T10:00:00Z',
  };

  await mockApi(page, {
    ...SIGNED_IN,
    'POST /api/mail/mailboxes/default/compose': { body: draft },
    'GET /api/mail/compose/d-b7': { body: draft },
    'PATCH /api/mail/compose/d-b7': (body) => {
      const patch = (body ?? {}) as { to_addrs?: { email: string }[]; subject?: string };
      return {
        body: {
          ...draft,
          to_addrs: patch.to_addrs ?? draft.to_addrs,
          subject: patch.subject ?? draft.subject,
          updated_at: '2026-10-28T10:00:01Z',
        },
      };
    },
    'POST /api/mail/compose/d-b7/send': {
      status: 422,
      body: {
        detail: {
          code: 'recipient_not_allowed',
          blocked: ['zakaznik@firma.sk'],
          allowlist: ['qa@example.test'],
          show_allowlist: true,
        },
      },
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
  await page.getByLabel('Komu').fill('zakaznik@firma.sk');
  await page.getByLabel('Predmet').fill('Test B7');
  await page.getByRole('button', { name: 'Odoslať' }).click();

  const banner = page.getByTestId('compose-send-error');
  await expect(banner).toBeVisible({ timeout: 2_000 });
  await expect(banner).toContainText('Testovací server smie posielať len na povolené adresy');
  await expect(banner).toContainText('zakaznik@firma.sk');
  // Draft stays open for edit
  await expect(page.getByLabel('Komu')).toHaveValue('zakaznik@firma.sk');
});
