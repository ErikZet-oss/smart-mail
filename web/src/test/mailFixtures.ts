import type { Folder, FoldersView, MessageDetail, MessagesList, Quota } from '../features/mail/mailApi';
import type { Prefs } from '../features/prefs/prefsApi';

let seq = 0;
const folder = (name: string, special: Folder['special_use'], unread = 0, total = unread, depth = 0): Folder => ({
  id: `f-${++seq}`,
  name,
  label: name.split('/').pop() ?? name,
  parent_id: null,
  depth,
  special_use: special,
  unread,
  total,
  selectable: true,
});

/** Fictional folder column like the customer's Roundcube (D21): special folders first, own folders alphabetically. */
export function foldersView(email = 'pilot@smartmail.test', quota: Quota | null = null): FoldersView {
  seq = 0;
  const folders = [
    folder('INBOX', 'inbox', 5, 15),
    folder('Drafts', 'drafts', 0, 1),
    folder('Sent', 'sent', 0, 4),
    folder('Junk', 'junk', 2, 2),
    folder('Trash', 'trash', 1, 3),
    folder('Archív', null, 0, 0),
    folder('Dodávatelia', null, 3, 9),
    folder('Faktúry', null, 0, 5220),
    folder('Senica', null, 0, 0),
  ];
  return {
    mailbox: { id: 'mb-1', email, unread: 5, sync_state: 'ok' },
    folders,
    quota: quota ?? { used_kb: 819, limit_kb: 2048, percent: 40, level: 'normal' },
    sync: { state: 'ok', error: null, last_synced_at: '2026-10-26T08:00:00Z' },
  };
}

export const defaultPrefs: Prefs = {
  list: {
    sort: 'date_received',
    sort_dir: 'desc',
    mode: 'list',
    density: 'compact',
    page_size: 50,
    show_ai_summary: true,
    mark_read: 'delay3',
    after_delete: 'next',
  },
  ui: { theme: 'light', classic: false, remote_images: 'known', prefer_html: true },
};

export function messagesList(folderId: string, total = 2): MessagesList {
  const messages = Array.from({ length: Math.min(total, 2) }, (_, i) => ({
    id: `m-${i + 1}`,
    thread_id: `t-${i + 1}`,
    folder_id: folderId,
    uid: i + 1,
    subject: i === 0 ? 'Kópia faktúry 2026123' : 'Cenová ponuka M10x30',
    from_name: i === 0 ? 'Ján Novák' : 'Petra Kováčová',
    from_email: i === 0 ? 'novak@abcstav.example' : 'petra@example.test',
    preview: 'Dobrý deň…',
    received_at: '2026-10-26T07:42:00Z',
    sent_at: '2026-10-26T07:42:00Z',
    size: 1200,
    seen: i !== 0,
    flagged: false,
    answered: false,
    has_attachments: i === 0,
    thread_count: 1,
  }));
  return {
    mode: 'list',
    total,
    page: 1,
    page_size: 50,
    messages,
    threads: [],
    prefs: defaultPrefs.list,
  };
}

export function messageDetail(id = 'm-1'): MessageDetail {
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

/** Handlers for `mockApi` of the W2 shell + list. */
export function mailHandlers(view: FoldersView = foldersView()) {
  const inbox = view.folders.find((f) => f.special_use === 'inbox')!;
  const list = messagesList(inbox.id, inbox.total);
  return {
    'GET /api/mail/mailboxes': { body: [view.mailbox] },
    'GET /api/mail/mailboxes/default/folders': { body: view },
    [`GET /api/mail/mailboxes/default/folders/${inbox.id}/messages`]: { body: list },
    'GET /api/mail/prefs': { body: defaultPrefs },
    'PUT /api/mail/prefs': { body: defaultPrefs },
    'GET /api/mail/mailboxes/default/messages/m-1': { body: messageDetail('m-1') },
    'GET /api/mail/mailboxes/default/messages/m-2': { body: messageDetail('m-2') },
  };
}
