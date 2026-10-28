import { expect, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

const SIGNED_IN = { 'GET /api/auth/me': { body: ME }, 'GET /api/auth/persons': { body: ME_PICKER } };

/** Fictional „Karta“ — table, inline styles, CID logo. Same shape as the settings preview. */
const SIGNATURE = [
  '<p style="margin:0 0 8px;font-family:Arial,sans-serif;font-size:14px;color:var(--text-primary)">S pozdravom,</p>',
  '<table cellpadding="0" cellspacing="0" style="border-collapse:collapse;border-left:3px solid var(--border-strong);font-family:Arial,sans-serif">',
  '<tr>',
  '<td style="padding:10px 14px;vertical-align:middle">',
  '<div style="width:72px;height:80px;background:var(--brand-primary-600);color:var(--text-on-primary);text-align:center;line-height:80px;font-weight:700;font-size:16px;clip-path:polygon(50% 0,100% 25%,100% 75%,50% 100%,0 75%,0 25%)">JT</div>',
  '</td>',
  '<td style="padding:10px 8px;vertical-align:middle">',
  '<div style="font-weight:700;font-size:14px;letter-spacing:0.04em;text-transform:uppercase;color:var(--text-primary)">Jana Testová</div>',
  '<div style="color:var(--brand-primary-600);font-size:13px">obchod</div>',
  '<div style="height:2px;background:var(--brand-primary-600);width:220px;margin:4px 0"></div>',
  '<div style="font-size:12px;color:var(--text-secondary)">+421 900 000 000 · Priemyselná 1, Senica</div>',
  '<div style="font-size:12px;color:var(--text-secondary)">jana@smartsro.sk · www.smartsro.sk</div>',
  '</td>',
  '<td style="padding:10px 14px;vertical-align:middle;text-align:center">',
  '<img src="cid:logo@smartmail" alt="SMART" width="96" height="33">',
  '<div style="font-size:11px;letter-spacing:0.06em;color:var(--text-tertiary)">Spojovací materiál</div>',
  '</td>',
  '</tr></table>',
].join('');

test('W4 signature stays a card, not plain text', async ({ page }) => {
  const draft = {
    id: 'd-28',
    mailbox_id: 'mb-1',
    mode: 'new',
    identity_id: 'id-1',
    to_addrs: [{ name: 'Peter Hudec', email: 'peter@kovo.example' }],
    cc_addrs: [],
    bcc_addrs: [],
    subject: 'Cenová ponuka',
    body_html: `<p>Dobrý deň,</p><div data-sm-signature="1">${SIGNATURE}</div>`,
    body_text: 'Dobrý deň,',
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
    updated_at: '2026-10-28T12:00:00Z',
  };
  await mockApi(page, {
    ...SIGNED_IN,
    'POST /api/mail/mailboxes/default/compose': { body: draft },
    'GET /api/mail/compose/d-28': { body: draft },
    'PATCH /api/mail/compose/d-28': { body: draft },
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
  const block = page.locator('.signature-block');
  await expect(block).toBeVisible();
  await expect(block.locator('table')).toBeVisible();
  await expect(block).toContainText('Jana Testová');
  await expect(block).toContainText('obchod');
  await expect(block.locator('img[alt="SMART"]')).toBeVisible();
  await expect(page.locator('.compose-editor')).toContainText('Dobrý deň');
  await expect(block).toHaveAttribute('contenteditable', 'false');
  await shot(page, 'issue28-W4-signature');
});
