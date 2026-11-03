import { DEFAULT_PREFS, expect, foldersView, ME, ME_PICKER, mockApi, shot, test } from './fixtures';

/** #205 FileTypeIcon on attachments (Figma 199:94925, AttachmentChip 11:823, AttachmentCard 199:95544). Fictional. */
const att = (id: string, filename: string, content_type: string, av_status = 'clean') => ({
  id,
  filename,
  content_type,
  size: 86_016,
  is_inline: false,
  av_status,
});
const ATTACHMENTS = [
  att('a-1', 'Faktura_FV2026-0123.pdf', 'application/pdf'),
  att('a-2', 'Cennik_2026.xlsx', 'application/octet-stream'),
  att('a-3', 'foto-paleta.JPG', 'image/jpeg'),
  att('a-4', 'podklady.zip', 'application/zip'),
  att('a-5', 'virus.pdf', 'application/pdf', 'infected'),
];

async function openMessage(page: import('@playwright/test').Page) {
  const view = foldersView();
  const inbox = view.folders.find((f) => f.special_use === 'inbox') ?? view.folders[0];
  if (!inbox) throw new Error('no inbox');
  const row = {
    id: 'm-1',
    thread_id: 't-1',
    folder_id: inbox.id,
    uid: 1,
    subject: 'Faktúra a podklady',
    from_name: 'Ján Novák',
    from_email: 'novak@abcstav.example',
    preview: 'Posielam faktúru a podklady…',
    received_at: '2026-11-03T07:42:00Z',
    sent_at: '2026-11-03T07:42:00Z',
    size: 1200,
    seen: true,
    flagged: false,
    answered: false,
    has_attachments: true,
    thread_count: 1,
  };
  await mockApi(page, {
    'GET /api/auth/me': { body: ME },
    'GET /api/auth/persons': { body: ME_PICKER },
    'GET /api/mail/mailboxes/default/folders': { body: view },
    [`GET /api/mail/mailboxes/default/folders/${inbox.id}/messages`]: {
      body: {
        mode: 'list',
        total: 1,
        page: 1,
        page_size: 50,
        messages: [row],
        threads: [],
        prefs: DEFAULT_PREFS.list,
      },
    },
    'GET /api/mail/mailboxes/default/messages/m-1': {
      body: {
        ...row,
        message_id: '<1@example.test>',
        to: [{ name: null, email: 'pilot@smartmail.test' }],
        cc: [],
        body_text: 'Dobrý deň, posielam faktúru a podklady.',
        body_html_sanitized: '<p>Dobrý deň, posielam faktúru a podklady.</p>',
        attachments: ATTACHMENTS,
        auth_results: null,
        thread_status: 'open',
        snoozed_until: null,
        assignee_id: null,
        remote_images_offered: false,
        remote_images_mode: 'never',
      },
    },
  });
  await page.goto('/mail/default/inbox');
  await page.getByText('Faktúra a podklady').first().click();
}

test('#205 W2c / M3: every attachment shows its file type @mobile', async ({ page }, info) => {
  await openMessage(page);
  const items = page.getByTestId('attachment');
  await expect(items).toHaveCount(5);
  await expect(items.nth(0)).toHaveAttribute('data-file-type', 'pdf');
  await expect(items.nth(1)).toHaveAttribute('data-file-type', 'xls'); // octet-stream: the extension wins
  await expect(items.nth(2)).toHaveAttribute('data-file-type', 'img');
  await expect(items.nth(3)).toHaveAttribute('data-file-type', 'zip');
  await expect(items.nth(0)).toHaveAttribute('aria-label', 'PDF, Faktura_FV2026-0123.pdf, 84 kB');
  // infected: the shield wins over the type icon
  await expect(items.nth(4).getByTestId('file-type-icon')).toHaveCount(0);
  await expect(items.nth(0).getByTestId('file-type-icon')).toHaveAttribute('data-file-type', 'pdf');
  if (info.project.name !== 'desktop') await expect(items.nth(0)).toContainText('PDF · 84 kB'); // AttachmentCard
  await shot(page, `issue205-attachments-${info.project.name}`);
});
