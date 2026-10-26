import { api } from '../../lib/api';

export type SpecialUse = 'inbox' | 'drafts' | 'sent' | 'junk' | 'trash';

export type MailboxSummary = { id: string; email: string; unread: number; sync_state: string };

export type Folder = {
  id: string;
  name: string;
  label: string;
  parent_id: string | null;
  depth: number;
  special_use: SpecialUse | null;
  unread: number;
  total: number;
  selectable: boolean;
};

export type QuotaLevel = 'normal' | 'warning' | 'danger';
export type Quota = { used_kb: number; limit_kb: number; percent: number; level: QuotaLevel };

export type FoldersView = {
  mailbox: MailboxSummary;
  folders: Folder[];
  quota: Quota | null;
  sync: { state: string; error: string | null; last_synced_at: string | null };
};

export type FolderAction = 'mark-read' | 'empty' | 'compact';

const base = (mailbox: string) => `/api/mail/mailboxes/${encodeURIComponent(mailbox)}`;

export const MAILBOXES_KEY = ['mail', 'mailboxes'] as const;
export const foldersKey = (mailbox: string) => ['mail', 'folders', mailbox] as const;

export const fetchMailboxes = () => api<MailboxSummary[]>('GET', '/api/mail/mailboxes');

export const fetchFolders = (mailbox: string) => api<FoldersView>('GET', `${base(mailbox)}/folders`);

export const refreshMailbox = (mailbox: string) => api<FoldersView>('POST', `${base(mailbox)}/refresh`, {});

export const runFolderAction = (mailbox: string, folderId: string, action: FolderAction) =>
  api<FoldersView>('POST', `${base(mailbox)}/folders/${folderId}/${action}`, {});

export const createFolder = (mailbox: string, parentId: string | null, name: string) =>
  api<FoldersView>('POST', `${base(mailbox)}/folders`, { parent_id: parentId, name });

export const renameFolder = (mailbox: string, folderId: string, name: string) =>
  api<FoldersView>('PATCH', `${base(mailbox)}/folders/${folderId}`, { name });

export const deleteFolder = (mailbox: string, folderId: string) =>
  api<FoldersView>('DELETE', `${base(mailbox)}/folders/${folderId}`);

/** Trash and junk can be emptied (G3, Roundcube). */
export const EMPTYABLE: ReadonlySet<SpecialUse> = new Set(['trash', 'junk']);

/** URL segment of a folder: the special-use key for special folders (`/mail/default/inbox`), else its id. */
export function folderRef(folder: Folder): string {
  return folder.special_use ?? folder.id;
}

export function findFolder(folders: Folder[], ref: string): Folder | undefined {
  return folders.find((f) => f.special_use === ref) ?? folders.find((f) => f.id === ref);
}

/** "5220" → "5 220" (Slovak grouping, non-breaking space like Figma). */
export function formatCount(value: number): string {
  return new Intl.NumberFormat('sk-SK').format(value);
}
