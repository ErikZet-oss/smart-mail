import { api } from '../../lib/api';

export type NotificationKind = 'sync_failed' | 'assigned';

export type NotificationItem = {
  id: string;
  kind: NotificationKind;
  created_at: string;
  unread: boolean;
  href: string | null;
  /** Machine params — UI copy comes from sk.json. */
  params: {
    mailbox_email?: string;
    error_code?: string;
    subject?: string;
  };
};

export type NotificationsList = { items: NotificationItem[]; unread_count: number };

export const NOTIFS_KEY = ['notifications'] as const;

export const fetchNotifications = () => api<NotificationsList>('GET', '/api/notifications');

export const dismissNotifications = (body: { ids?: string[]; all?: boolean }) =>
  api<{ ok: boolean }>('POST', '/api/notifications/dismiss', body);

const SYNC_CODES = new Set(['auth_failed', 'host_not_allowed', 'no_credentials', 'unavailable']);

/** Map API error_code → i18n key under notifs.syncErrors (never show raw server text). */
export function syncErrorKey(code: string | undefined): string {
  if (code && SYNC_CODES.has(code)) return code;
  return 'unavailable';
}
