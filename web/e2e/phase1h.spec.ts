import type { Page } from '@playwright/test';

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
    body_html_sanitized: '<p>Dobrý deň,</p><p>prosím o zaslanie kópie faktúry 2026123.</p>',
    attachments: [],
    auth_results: null,
    thread_status: 'open',
    snoozed_until: null,
    assignee_id: null,
  };
}

const COMPOSE_DRAFT = {
  id: 'd-1',
  mailbox_id: 'mb-1',
  mode: 'new',
  identity_id: 'id-1',
  to_addrs: [],
  cc_addrs: [],
  bcc_addrs: [],
  subject: '',
  body_html: '<p></p><div data-sm-signature="1"><p><strong>Jana Testová</strong></p></div>',
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
  attachments: [],
  checks: [],
  updated_at: '2026-10-26T12:00:00Z',
};

async function mockMail(
  page: Page,
  extras: Record<string, { body: unknown; status?: number } | (() => { body: unknown })> = {},
) {
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
    'POST /api/mail/mailboxes/default/compose': { body: COMPOSE_DRAFT },
    'GET /api/mail/compose/d-1': { body: COMPOSE_DRAFT },
    'PATCH /api/mail/compose/d-1': { body: COMPOSE_DRAFT },
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
    ...extras,
  });
  return { inbox, view };
}

const person = (id: string, first: string, last: string, fn: string, manager = false) => ({
  id,
  first_name: first,
  last_name: last,
  full_name: `${first} ${last}`,
  role: 'sales',
  function: fn,
  is_manager: manager,
});
const PEOPLE = [
  person('p-peter', 'Peter', 'Hudák', 'vedúci pobočky', true),
  person('p-jana', 'Jana', 'Nováková', 'obchod'),
  person('p-marek', 'Marek', 'Kováč', 'sklad'),
];

test.describe('Phase 1h-a: PWA + mobile shell M0–M4', () => {
  test('M0 Kto ste? @mobile', async ({ page }, info) => {
    test.skip(info.project.name !== 'mobile', 'mobile frame');
    const state = { current: null as (typeof PEOPLE)[number] | null, last: 'p-jana' as string | null };
    const me = () => ({
      account_id: 'a-senica',
      email: 'senica@smartsro.sk',
      kind: 'branch',
      branch: 'Senica',
      person: state.current,
      needs_person: state.current === null,
      read_only: state.current === null,
    });
    await mockApi(page, {
      'GET /api/auth/me': () => ({ body: me() }),
      'GET /api/auth/persons': () => ({
        body: {
          branch: 'Senica',
          email: 'senica@smartsro.sk',
          persons: PEOPLE,
          current_person_id: state.current?.id ?? null,
          last_person_id: state.last,
          idle_ask_minutes: null,
        },
      }),
    });
    await page.goto('/who');
    await expect(page.getByRole('heading', { name: 'Kto ste?' })).toBeVisible();
    await expect(page.getByRole('switch', { name: 'Zapamätať na tomto telefóne' })).toBeVisible();
    await shot(page, 'phase1h-M0-who');
  });

  test('M1 list + bottom nav + FAB @mobile', async ({ page }, info) => {
    test.skip(info.project.name !== 'mobile', 'mobile frame');
    await mockMail(page);
    await page.goto('/mail/default/inbox');
    await expect(page.getByTestId('mobile-shell')).toBeVisible();
    await expect(page.getByTestId('bottom-nav')).toBeVisible();
    await expect(page.getByTestId('mobile-app-bar')).toBeVisible();
    await expect(page.getByTestId('compose-fab')).toBeVisible();
    await expect(page.getByText('Kópia faktúry 2026123')).toBeVisible();
    await expect(page.getByRole('link', { name: 'E-mail' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Kontakty' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Viac' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Dnes' })).toHaveCount(0);
    await expect(page.getByRole('link', { name: 'Doklady' })).toHaveCount(0);
    await shot(page, 'phase1h-M1-list');
  });

  test('M1 dark @mobile', async ({ page }, info) => {
    test.skip(info.project.name !== 'mobile', 'mobile frame');
    await mockMail(page, {
      'GET /api/mail/prefs': {
        body: { ...DEFAULT_PREFS, ui: { ...DEFAULT_PREFS.ui, theme: 'dark' } },
      },
    });
    await page.goto('/mail/default/inbox');
    await expect(page.getByTestId('bottom-nav')).toBeVisible();
    await shot(page, 'phase1h-M1-dark');
  });

  test('M2 folders drawer @mobile', async ({ page }, info) => {
    test.skip(info.project.name !== 'mobile', 'mobile frame');
    await mockMail(page);
    await page.goto('/mail/default/inbox');
    await page.getByTestId('mobile-app-bar').getByRole('button', { name: 'Priečinky' }).first().click();
    await expect(page.getByTestId('folder-drawer')).toBeVisible();
    await expect(page.getByRole('dialog', { name: 'Priečinky' })).toBeVisible();
    await shot(page, 'phase1h-M2-folders');
  });

  test('M3 thread detail hides bottom nav @mobile', async ({ page }, info) => {
    test.skip(info.project.name !== 'mobile', 'mobile frame');
    await mockMail(page);
    await page.goto('/mail/default/inbox');
    await page.getByText('Kópia faktúry 2026123').click();
    await expect(page).toHaveURL(/\/mail\/default\/inbox\/t-1/);
    await expect(page.getByTestId('mobile-thread')).toBeVisible();
    await expect(page.getByTestId('bottom-nav')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Späť' })).toBeVisible();
    await shot(page, 'phase1h-M3-detail');
  });

  test('M4 compose full screen @mobile', async ({ page }, info) => {
    test.skip(info.project.name !== 'mobile', 'mobile frame');
    await mockMail(page);
    await page.goto('/compose?mailbox=default');
    await expect(page.getByTestId('compose-screen')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Nová správa' })).toBeVisible();
    await expect(page.getByTestId('bottom-nav')).toHaveCount(0);
    await shot(page, 'phase1h-M4-compose');
  });

  test('M1 long-press multi-select @mobile', async ({ page }, info) => {
    test.skip(info.project.name !== 'mobile', 'mobile frame');
    await mockMail(page);
    await page.goto('/mail/default/inbox');
    const row = page.getByRole('option').filter({ hasText: 'Kópia faktúry 2026123' });
    await row.dispatchEvent('touchstart');
    await page.waitForTimeout(500);
    await row.dispatchEvent('touchend');
    await expect(page.getByText('Vybraté: 1')).toBeVisible();
    await shot(page, 'phase1h-M1-multiselect');
  });

  test('desktop W2 still uses rail (no bottom nav)', async ({ page }, info) => {
    test.skip(info.project.name !== 'desktop', 'desktop only');
    await mockMail(page);
    await page.goto('/mail/default/inbox');
    await expect(page.getByTestId('bottom-nav')).toHaveCount(0);
    await expect(page.getByRole('navigation', { name: 'Hlavná navigácia' })).toBeVisible();
    await shot(page, 'phase1h-W2-desktop-rail');
  });

  test('install meta + apple icon present', async ({ page }, info) => {
    test.skip(info.project.name !== 'desktop', 'once');
    await mockMail(page);
    await page.goto('/mail/default/inbox');
    await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute('content', '#0F75BC');
    await expect(page.locator('link[rel="apple-touch-icon"]')).toHaveAttribute('href', '/apple-touch-icon.png');
  });

  // Allows the real SW (blocked by default so mockApi works) to prove denylist behaviour.
  test.describe('PWA service worker', () => {
    test.use({ serviceWorkers: 'allow' });

    test('SW navigateFallbackDenylist: /api/version stays JSON after SW registers', async ({ page }, info) => {
      test.skip(info.project.name !== 'desktop', 'once');
      await mockMail(page);
      await page.goto('/mail/default/inbox');
      await page.waitForFunction(async () => {
        if (!('serviceWorker' in navigator)) return false;
        const reg = await navigator.serviceWorker.ready;
        return Boolean(reg.active);
      });
      // Without denylist the SW would serve index.html for this navigation (breaks OIDC /api returns).
      // Preview middleware stubs JSON when no backend is running (CI).
      const response = await page.goto('/api/version');
      expect(response, 'expected a network response for /api/version').toBeTruthy();
      if (!response) return;
      expect(response.status()).toBe(200);
      expect(response.headers()['content-type'] ?? '').toMatch(/application\/json/);
      const body = (await response.json()) as { version?: string; env?: string };
      expect(body.version).toEqual(expect.any(String));
      expect(body.version?.length).toBeGreaterThan(0);
      // Must not be the SPA shell
      await expect(page.locator('#root')).toHaveCount(0);
    });
  });
});

test.describe('pilot: long message on mobile', () => {
  test('M3 long message scrolls to the end @mobile', async ({ page }, info) => {
    test.skip(info.project.name !== 'mobile', 'mobile frame');
    const long = detail();
    long.body_html_sanitized =
      Array.from({ length: 120 }, (_, i) => `<p>Riadok ${i + 1} dlhej objednávky.</p>`).join('') +
      '<p id="koniec">Koniec správy</p><table width="600"><tr><td>Široká tabuľka newslettera</td></tr></table>';
    await mockMail(page, { 'GET /api/mail/mailboxes/default/messages/m-1': { body: long } });
    await page.goto('/mail/default/inbox');
    await page.getByText('Kópia faktúry 2026123').click();
    await expect(page.getByTestId('mobile-thread')).toBeVisible();
    const end = page.getByText('Koniec správy');
    await expect(end).not.toBeInViewport();
    await page.mouse.move(195, 500);
    for (let i = 0; i < 40; i += 1) await page.mouse.wheel(0, 600);
    await expect(end).toBeInViewport();
    // no horizontal page overflow from a fixed-width newsletter table
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });
});

test.describe('pilot: remote images bar', () => {
  test('W3 unknown sender gets the bar; "Vždy od tohto odosielateľa" adds a contact and shows images', async ({
    page,
  }, info) => {
    test.skip(info.project.name !== 'desktop', 'desktop frame');
    const remote = {
      ...detail(),
      body_html_sanitized:
        '<p>Akcia</p><img alt="banner" src="about:blank#smartmail-remote" data-remote-src="/api/mail/image-proxy?u=x&amp;s=y">',
      remote_images_offered: true,
      remote_images_auto: false,
      remote_images_mode: 'known',
    };
    let created: unknown = null;
    await mockMail(page, {
      'GET /api/mail/mailboxes/default/messages/m-1': { body: remote },
      'GET /api/contacts/books': { body: [{ id: 'b-1', kind: 'personal', name: 'Osobné kontakty' }] },
      'POST /api/contacts/books/b-1/contacts': () => {
        created = true;
        return { body: { id: 'c-1' } };
      },
    });
    // the proxied image itself (an <img> 401 would not log out, but keep the run free of unmocked calls, #62)
    await page.route('**/api/mail/image-proxy?*', (route) =>
      route.fulfill({ status: 200, contentType: 'image/gif', body: Buffer.from('R0lGODlhAQABAAAAACw=', 'base64') }),
    );
    await page.goto('/mail/default/inbox');
    await page.getByText('Kópia faktúry 2026123').click();
    await expect(page.getByText('Vzdialené obrázky sú zablokované.')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Zobraziť obrázky' })).toBeVisible();
    await page.getByRole('button', { name: 'Vždy od tohto odosielateľa' }).click();
    await expect(page.getByText('Vzdialené obrázky sú zablokované.')).toHaveCount(0);
    await expect(page.locator('img[alt="banner"]')).toHaveAttribute('src', /image-proxy/);
    expect(created).toBe(true);
  });
});

test.describe('pilot: drop files into compose', () => {
  test('W4 dropping two files attaches both and does not show the G7 document toast', async ({ page }, info) => {
    test.skip(info.project.name !== 'desktop', 'desktop frame');
    const uploads: string[] = [];
    await mockMail(page, {
      'POST /api/mail/compose/d-1/attachments': () => {
        uploads.push('file');
        return {
          body: {
            ...COMPOSE_DRAFT,
            attachments: uploads.map((_, i) => ({
              id: `a-${i + 1}`,
              filename: i === 0 ? 'cennik.pdf' : 'foto.png',
              content_type: i === 0 ? 'application/pdf' : 'image/png',
              size: 1200,
              av_status: 'clean',
              is_inline: false,
              content_id: null,
            })),
          },
        };
      },
    });
    await page.goto('/compose?mailbox=default');
    const screen = page.getByTestId('compose-screen');
    await expect(screen).toBeVisible();
    await expect(page.getByLabel('Komu')).toBeEnabled();
    const transfer = await page.evaluateHandle(() => {
      const dt = new DataTransfer();
      dt.items.add(new File(['%PDF-1.4'], 'cennik.pdf', { type: 'application/pdf' }));
      dt.items.add(new File(['png'], 'foto.png', { type: 'image/png' }));
      return dt;
    });
    await screen.dispatchEvent('dragenter', { dataTransfer: transfer });
    await screen.dispatchEvent('dragover', { dataTransfer: transfer });
    await expect(page.getByText('Pustite súbory sem – priložia sa k správe')).toBeVisible();
    await screen.dispatchEvent('drop', { dataTransfer: transfer });
    await expect(page.getByText('foto.png')).toBeVisible();
    await expect(page.getByText('cennik.pdf')).toBeVisible();
    expect(uploads).toHaveLength(2);
    await expect(page.getByText('Nahrávanie dokladov zatiaľ nie je dostupné – súbor sme neotvorili.')).toHaveCount(0);
  });
});

test.describe('pilot: paste a screenshot into compose', () => {
  test('W4 Ctrl+V of a Win+Shift+S screenshot uploads it as an inline image in the text', async ({ page }) => {
    let uploads = 0;
    await mockMail(page, {
      'POST /api/mail/compose/d-1/attachments': () => {
        uploads += 1;
        return {
          body: {
            ...COMPOSE_DRAFT,
            attachments: [
              {
                id: 'a-1',
                filename: 'snimka.png',
                content_type: 'image/png',
                size: 900,
                av_status: 'clean',
                is_inline: true,
                content_id: 'snimka-1@smartmail',
              },
            ],
          },
        };
      },
    });
    await page.goto('/compose?mailbox=default');
    await expect(page.getByLabel('Komu')).toBeEnabled();
    const editor = page.locator('.ProseMirror').first();
    await editor.click();
    await editor.evaluate((node) => {
      const dt = new DataTransfer();
      dt.items.add(new File([new Uint8Array([137, 80, 78, 71])], 'image.png', { type: 'image/png' }));
      node.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }));
    });
    await expect.poll(() => uploads).toBe(1);
    const img = editor.locator('img[data-cid-src="cid:snimka-1@smartmail"]');
    await expect(img).toHaveCount(1);
    // the browser shows the draft's own copy; the document keeps cid: for the sent mail
    await expect(img).toHaveAttribute('src', '/api/mail/compose/d-1/inline/snimka-1%40smartmail');
  });
});

function must<T>(value: T | null | undefined): T {
  if (value === null || value === undefined) throw new Error('missing value');
  return value;
}

// #185 Erik's Android test (360–412 px): nothing outside the viewport, nothing under the FAB. Figma M1 `83:2974`,
// M1 multi-select `82:1534`, M3 `83:3117` / `83:2434`.
for (const size of [
  { width: 360, height: 780 },
  { width: 412, height: 915 },
]) {
  test.describe(`#185 mobile ${size.width}×${size.height} @mobile`, () => {
    test.use({ viewport: size });

    test(`#185 M1 bulk bar fits ${size.width} px; FAB never covers the last row`, async ({ page }, info) => {
      test.skip(info.project.name !== 'mobile', 'mobile frame');
      // a long folder: 30 rows on the first page of 380, so the end of the list really meets the FAB and the pager
      const inboxId = must(foldersView().folders.find((f) => f.special_use === 'inbox')).id;
      const base = inboxList(inboxId);
      const many = Array.from({ length: 30 }, (_, i) => ({
        ...must(base.messages[i % 2]),
        id: `m-${i + 1}`,
        thread_id: `t-${i + 1}`,
        subject: i === 29 ? 'Posledný riadok zoznamu' : `${must(base.messages[i % 2]).subject} ${i + 1}`,
      }));
      await mockMail(page, {
        [`GET /api/mail/mailboxes/default/folders/${inboxId}/messages`]: {
          body: { ...base, total: 380, page: 2, page_size: 30, messages: many },
        },
      });
      await page.goto('/mail/default/inbox');
      const last = page.getByRole('option').filter({ hasText: 'Posledný riadok zoznamu' });
      await expect(last).toBeVisible();
      // scroll to the end of the list: the last row ends above the FAB
      const list = page.getByTestId('folder-message-list');
      await list.evaluate((n) => n.scrollTo(0, n.scrollHeight));
      await page.waitForTimeout(300); // the end of the list may load more rows (#185)
      await list.evaluate((n) => n.scrollTo(0, n.scrollHeight));
      const fab = await page.getByTestId('compose-fab').boundingBox();
      const row = await last.boundingBox();
      expect(fab && row).toBeTruthy();
      expect(must(row).y + must(row).height).toBeLessThanOrEqual(must(fab).y);
      const pager = await page.getByRole('button', { name: 'Ďalšia strana' }).boundingBox();
      if (pager) expect(pager.y + pager.height).toBeLessThanOrEqual(must(fab).y);
      await shot(page, `issue185-M1-${size.width}`);

      const first = page.getByRole('option').filter({ hasText: 'Kópia faktúry 2026123 1' }).first();
      await first.scrollIntoViewIfNeeded();
      await first.dispatchEvent('touchstart');
      await page.waitForTimeout(500);
      await first.dispatchEvent('touchend');
      const bar = page.getByTestId('bulk-toolbar');
      await expect(bar.getByText('Vybraté: 1')).toBeVisible();
      for (const el of await bar.locator('button, span').all()) {
        const box = await el.boundingBox();
        expect(box).toBeTruthy();
        expect(must(box).x).toBeGreaterThanOrEqual(0);
        expect(must(box).x + must(box).width).toBeLessThanOrEqual(size.width);
        expect(must(box).height).toBeLessThanOrEqual(56); // no wrapped labels
      }
      await shot(page, `issue185-M1-select-${size.width}`);
      await bar.getByRole('button', { name: 'Viac' }).click();
      for (const name of ['Označiť ako prečítané', 'Archivovať', 'Presunúť']) {
        await expect(page.getByRole('menuitem', { name })).toBeInViewport();
      }
    });

    test(`#185 M3 action bar and images banner fit ${size.width} px`, async ({ page }, info) => {
      test.skip(info.project.name !== 'mobile', 'mobile frame');
      await mockMail(page, {
        'GET /api/mail/mailboxes/default/messages/m-1': {
          body: {
            ...detail(),
            body_html_sanitized:
              '<p>Akcia</p><img alt="banner" src="about:blank#smartmail-remote" data-remote-src="x">',
            remote_images_offered: true,
            remote_images_auto: false,
            remote_images_mode: 'known',
          },
        },
      });
      await page.goto('/mail/default/inbox/t-1');
      const bar = page.getByTestId('m3-action-bar');
      await expect(bar).toBeVisible();
      const labels = ['Odpovedať', 'Všetkým', 'Poslať ďalej', 'Viac'];
      for (const name of labels) await expect(bar.getByText(name, { exact: true })).toBeVisible();
      for (const el of await bar.getByRole('button').all()) {
        const box = await el.boundingBox();
        expect(must(box).x).toBeGreaterThanOrEqual(0);
        expect(must(box).x + must(box).width).toBeLessThanOrEqual(size.width);
      }
      // labels are not cut: each label's text fits its button
      for (const el of await bar.locator('span.type-micro').all()) {
        expect(await el.evaluate((n) => n.scrollWidth <= n.clientWidth)).toBe(true);
      }
      // the images banner: text and actions do not overlap
      const text = page.getByText('Vzdialené obrázky sú zablokované.');
      const show = page.getByRole('button', { name: 'Zobraziť obrázky' });
      const always = page.getByRole('button', { name: 'Vždy od tohto odosielateľa' });
      const [t, s, a] = [await text.boundingBox(), await show.boundingBox(), await always.boundingBox()];
      const overlap = (p: typeof t, q: typeof t) =>
        !!p && !!q && p.x < q.x + q.width && q.x < p.x + p.width && p.y < q.y + q.height && q.y < p.y + p.height;
      expect(overlap(t, s) || overlap(t, a) || overlap(s, a)).toBe(false);
      expect(must(a).x + must(a).width).toBeLessThanOrEqual(size.width);
      await shot(page, `issue185-M3-${size.width}`);
      await bar.getByRole('button', { name: 'Viac' }).click();
      for (const name of ['Vymazať', 'Nevyžiadané', 'Vybavené']) {
        await expect(page.getByRole('menuitem', { name })).toBeInViewport();
      }
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow).toBeLessThanOrEqual(0);
    });
  });
}
