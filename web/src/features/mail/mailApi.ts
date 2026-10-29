import { api } from '../../lib/api';
import type { ListPrefs } from '../prefs/prefsApi';

export type SpecialUse = 'inbox' | 'drafts' | 'sent' | 'junk' | 'trash';

export type MailboxSummary = {
  id: string;
  email: string;
  unread: number;
  sync_state: string;
  ai_enabled?: boolean;
  ai_available?: boolean;
};

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

export function findFolder(folders: Folder[] | null | undefined, ref: string): Folder | undefined {
  if (!folders?.length) return undefined;
  return folders.find((f) => f.special_use === ref) ?? folders.find((f) => f.id === ref);
}

/** "5220" → "5 220" (Slovak grouping, non-breaking space like Figma). */
export function formatCount(value: number): string {
  return new Intl.NumberFormat('sk-SK').format(value);
}

export type MessageFilter = 'all' | 'unread' | 'flagged' | 'attachments';

export type MessageListItem = {
  id: string;
  thread_id: string | null;
  folder_id: string;
  uid: number;
  subject: string | null;
  from_name: string | null;
  from_email: string | null;
  preview: string | null;
  received_at: string | null;
  sent_at: string | null;
  size: number;
  seen: boolean;
  flagged: boolean;
  answered: boolean;
  forwarded?: boolean;
  has_attachments: boolean;
  thread_count: number;
  ai_category?: string | null;
  ai_priority?: string | null;
  ai_summary?: string | null;
  ai_language?: string | null;
  ai_confidence?: number | null;
  ai_note_codes?: string[];
};

export type AiCategory = {
  id: string;
  label_sk: string;
  description_sk: string;
  color_token: string;
  count: number;
};

export type ThreadListItem = {
  id: string;
  subject: string | null;
  from_name: string | null;
  from_email: string | null;
  preview: string | null;
  last_message_at: string | null;
  message_count: number;
  unread_count: number;
  flagged: boolean;
  has_attachments: boolean;
  status: string;
  snoozed_until: string | null;
  assignee_id: string | null;
  latest_message_id: string | null;
};

export type MessagesList = {
  mode: 'list' | 'conversations';
  total: number;
  page: number;
  page_size: number;
  messages: MessageListItem[];
  threads: ThreadListItem[];
  prefs: ListPrefs;
};

export type Addr = { name: string | null; email: string | null };

export type AttachmentOut = {
  id: string;
  filename: string;
  content_type: string;
  size: number;
  is_inline: boolean;
  av_status: string;
};

export type MessageDetail = {
  id: string;
  thread_id: string | null;
  folder_id: string;
  uid: number;
  message_id: string | null;
  subject: string | null;
  from_name: string | null;
  from_email: string | null;
  to: Addr[];
  cc: Addr[];
  sent_at: string | null;
  received_at: string | null;
  size: number;
  seen: boolean;
  flagged: boolean;
  answered: boolean;
  body_text: string | null;
  body_html_sanitized: string | null;
  attachments: AttachmentOut[];
  auth_results: Record<string, string> | null;
  thread_status: string | null;
  snoozed_until: string | null;
  assignee_id: string | null;
  ai_category?: string | null;
  ai_summary?: string | null;
  ai_language?: string | null;
  security_notes?: string[];
  /** Pilot #18 B6 — server may offer remote images via signed proxy (not raw https). */
  remote_images_offered?: boolean;
  remote_images_auto?: boolean;
  remote_images_mode?: 'never' | 'known' | 'always';
};

export type BulkAction =
  'mark_seen' | 'mark_unseen' | 'flag' | 'unflag' | 'delete' | 'junk' | 'archive' | 'move' | 'done';

export const messagesKey = (mailbox: string, folderId: string, page: number, filter: MessageFilter) =>
  ['mail', 'messages', mailbox, folderId, page, filter] as const;

export const messageKey = (mailbox: string, id: string) => ['mail', 'message', mailbox, id] as const;

export const fetchMessages = (
  mailbox: string,
  folderId: string,
  opts: { page?: number; pageSize?: number; filter?: MessageFilter; q?: string } = {},
) => {
  const params = new URLSearchParams();
  if (opts.page) params.set('page', String(opts.page));
  if (opts.pageSize) params.set('page_size', String(opts.pageSize));
  if (opts.filter && opts.filter !== 'all') params.set('filter', opts.filter);
  if (opts.q) params.set('q', opts.q);
  const qs = params.toString();
  return api<MessagesList>('GET', `${base(mailbox)}/folders/${folderId}/messages${qs ? `?${qs}` : ''}`);
};

export const aiCategoriesKey = (mailbox: string) => ['mail', 'ai-categories', mailbox] as const;

export const fetchAiCategories = (mailbox: string) =>
  api<{ categories: AiCategory[] }>('GET', `${base(mailbox)}/ai/categories`);

export const fetchCategoryMessages = (
  mailbox: string,
  category: string,
  opts: { page?: number; pageSize?: number; filter?: MessageFilter; q?: string } = {},
) => {
  const params = new URLSearchParams();
  if (opts.page) params.set('page', String(opts.page));
  if (opts.pageSize) params.set('page_size', String(opts.pageSize));
  if (opts.filter && opts.filter !== 'all') params.set('filter', opts.filter);
  if (opts.q) params.set('q', opts.q);
  const qs = params.toString();
  return api<{
    category: AiCategory;
    total: number;
    page: number;
    page_size: number;
    messages: MessageListItem[];
  }>('GET', `${base(mailbox)}/ai/views/${encodeURIComponent(category)}/messages${qs ? `?${qs}` : ''}`);
};

export const fetchMessage = (mailbox: string, id: string, markRead = true) =>
  api<MessageDetail>('GET', `${base(mailbox)}/messages/${id}${markRead ? '' : '?mark_read=false'}`);

export const patchFlags = (mailbox: string, id: string, body: { seen?: boolean; flagged?: boolean }) =>
  api<MessageDetail>('PATCH', `${base(mailbox)}/messages/${id}/flags`, body);

export const bulkMessages = (
  mailbox: string,
  body: { message_ids: string[]; action: BulkAction; dest_folder_id?: string },
) => api<{ ok: number }>('POST', `${base(mailbox)}/messages/bulk`, body);

export const snoozeThread = (mailbox: string, threadId: string, until: string | null) =>
  api<{ ok: string; status: string }>('POST', `${base(mailbox)}/threads/${threadId}/snooze`, { until });

export const assignThread = (mailbox: string, threadId: string, personId: string | null) =>
  api<{ ok: string; assignee_id: string | null }>('POST', `${base(mailbox)}/threads/${threadId}/assign`, {
    person_id: personId,
  });

export function attachmentUrl(mailbox: string, attachmentId: string): string {
  return `${base(mailbox)}/attachments/${attachmentId}`;
}

export function sourceUrl(mailbox: string, messageId: string): string {
  return `${base(mailbox)}/messages/${messageId}/source`;
}

export async function fetchSourceText(mailbox: string, messageId: string): Promise<string> {
  const response = await fetch(sourceUrl(mailbox, messageId), { credentials: 'same-origin' });
  if (!response.ok) throw new Error(`source ${response.status}`);
  return response.text();
}
