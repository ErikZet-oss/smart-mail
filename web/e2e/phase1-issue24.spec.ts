import { expect, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

const NAV = {
  sections: [
    {
      id: '03',
      path: 'identity',
      title: 'Identity',
      subs: [
        { id: '03a', path: 'list', title: 'Identity' },
        { id: '03b', path: 'profile', title: 'Môj profil' },
      ],
    },
    {
      id: '11',
      path: 'branches',
      title: 'Pobočky a osoby',
      subs: [{ id: '11c', path: 'signature', title: 'Šablóna podpisu' }],
    },
  ],
};

const KARTA =
  '<table style="border-collapse:collapse;font-family:Arial,sans-serif"><tr>' +
  '<td style="padding:8px"><img src="/logo-smart.svg" alt="SMART" width="96" height="33"></td>' +
  '<td style="padding:8px;font-size:14px"><strong>PETER HUDÁK</strong><br>Obchod' +
  '<br><img src="https://example.com/signature-photo.png" alt="Peter Hudák" width="72"></td>' +
  '</tr></table>';

test.describe('Issue 24 — signature editor', () => {
  test('paste Karta through the source dialog, save, and reopen', async ({ page }) => {
    let saved = '<p><strong>Jana Testová</strong><br/>Smart s.r.o.</p>';
    const identity = () => ({
      id: 'id-1',
      display_name: 'Jana Testová',
      email: 'jana@smartsro.sk',
      organization: 'Smart s.r.o.',
      is_default: true,
      signature_html: { sk: saved, cs: '', en: '', de: '' },
      signature_images: [],
    });
    await mockApi(page, {
      'GET /api/auth/me': { body: ME },
      'GET /api/auth/persons': { body: ME_PICKER },
      'GET /api/settings/nav': { body: NAV },
      'GET /api/settings/mailboxes/default/identities': () => ({ body: [identity()] }),
      'PUT /api/settings/identities/id-1': (body: unknown) => {
        const sent = body as { signature_html?: { sk?: string } };
        saved = sent.signature_html?.sk ?? saved;
        return {
          body: {
            ...identity(),
            signature_stripped: {},
          },
        };
      },
      'POST /api/settings/signature-remote-previews': { body: { previews: {} } },
    });
    await page.goto('/settings/identity/list');
    await expect(page.getByRole('button', { name: 'Zdrojový kód' })).toBeVisible();
    await page.getByRole('button', { name: 'Zdrojový kód' }).click();
    await page.getByRole('textbox', { name: 'Zdrojový kód' }).fill(KARTA);
    await page.getByRole('button', { name: 'Vložiť', exact: true }).click();
    await expect(page.getByText('PETER HUDÁK')).toBeVisible();
    await expect(page.getByRole('img', { name: 'Peter Hudák' })).toBeVisible();
    await page.getByRole('button', { name: 'Uložiť' }).click();
    await page.reload();
    await expect(page.getByText('PETER HUDÁK')).toBeVisible();
    await expect(page.getByRole('textbox', { name: 'Podpis' }).getByRole('img', { name: 'SMART' })).toBeVisible();
    await shot(page, 'issue24-W12-03a-karta');
  });

  test('branch mailbox in 03a is a preview and a link to section 11', async ({ page }) => {
    await mockApi(page, {
      'GET /api/auth/me': { body: { ...ME, kind: 'branch' } },
      'GET /api/auth/persons': { body: ME_PICKER },
      'GET /api/settings/nav': { body: NAV },
      'GET /api/settings/mailboxes/default/signature-context': {
        body: {
          mailbox_kind: 'branch',
          account_kind: 'branch',
          branch_managed: true,
          preview_html: '<p><strong>Peter Hudák</strong><br>Senica</p>',
          branch_id: 'b-1',
        },
      },
      'GET /api/settings/mailboxes/default/identities': { body: [] },
    });
    await page.goto('/settings/identity/list');
    await expect(page.getByText('Podpis pobočky – mení správca')).toBeVisible();
    await expect(page.getByText('Peter Hudák')).toBeVisible();
    await expect(page.getByRole('link', { name: 'Upraviť šablónu pobočky' })).toHaveAttribute(
      'href',
      '/settings/branches/signature',
    );
    await expect(page.getByRole('button', { name: 'Zdrojový kód' })).toHaveCount(0);
    await shot(page, 'issue24-W12-03a-branch-preview');
  });

  test('11c shows variable chips and the Karta / Text presets', async ({ page }) => {
    const admin = { ...ME, person: { ...ME.person, role: 'admin' } };
    await mockApi(page, {
      'GET /api/auth/me': { body: admin },
      'GET /api/auth/persons': { body: ME_PICKER },
      'GET /api/settings/nav': { body: NAV },
      'GET /api/settings/signature-presets': {
        body: {
          karta: {
            sk: '<table><tr><td>{meno} {priezvisko}</td><td>{logo}</td></tr></table>',
            cs: '<p>{meno}</p>',
            en: '<p>{meno}</p>',
            de: '<p>{meno}</p>',
          },
          text: {
            sk: '<p>S pozdravom</p><p><strong>{meno} {priezvisko}</strong></p>',
            cs: '<p>{meno}</p>',
            en: '<p>{meno}</p>',
            de: '<p>{meno}</p>',
          },
        },
      },
      'GET /api/settings/admin/branches': {
        body: [
          {
            id: 'b-1',
            name: 'Senica',
            address: 'Hlavná 1',
            phone: '034 000 000',
            hours: 'Po–Pi 8–16',
            mailbox_id: 'mb-1',
            mailbox_email: 'senica@smartsro.sk',
            signature_template_html: {
              sk: '<p>{meno} {priezvisko}</p>',
              cs: '',
              en: '',
              de: '',
            },
            signature_images: [],
            people: [
              {
                id: 'p-peter',
                first_name: 'Peter',
                last_name: 'Hudák',
                function: 'Obchod',
                role: 'sales',
                active: true,
                phone: '',
                mobile: '',
                personal_email: 'peter.hudak@example.com',
              },
            ],
          },
        ],
      },
    });
    await page.goto('/settings/branches/signature');
    await expect(page.getByRole('button', { name: '{meno}' })).toBeVisible();
    await expect(page.getByRole('button', { name: '{logo}' })).toBeVisible();
    await expect(page.getByText('Prázdne premenné sa pri odoslaní vynechajú')).toBeVisible();
    await expect(page.locator('div.bg-bg-subtle').getByText('Peter Hudák')).toBeVisible();
    await page.getByRole('button', { name: 'Text', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'Obnoviť predvolenú šablónu' });
    await dialog.getByRole('button', { name: 'Obnoviť predvolenú šablónu' }).click();
    await expect(page.getByRole('textbox', { name: 'Šablóna podpisu pobočky' }).getByText('S pozdravom')).toBeVisible();
    await shot(page, 'issue24-W12-11c-template');
  });
});
