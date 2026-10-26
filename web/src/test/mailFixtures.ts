import type { Folder, FoldersView, Quota } from '../features/mail/mailApi';

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

/** Handlers for `mockApi` of the W2 shell. */
export function mailHandlers(view: FoldersView = foldersView()) {
  return {
    'GET /api/mail/mailboxes': { body: [view.mailbox] },
    'GET /api/mail/mailboxes/default/folders': { body: view },
  };
}
