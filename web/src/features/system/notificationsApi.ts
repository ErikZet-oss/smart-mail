import { api } from '../../lib/api';

export type NotificationKind = 'sync_failed' | 'assigned';

export type NotificationItem = {
  id: string;
  kind: NotificationKind;
  title: string;
  body: string;
  created_at: string;
  unread: boolean;
  href: string | null;
};

export type NotificationsList = { items: NotificationItem[]; unread_count: number };

export const NOTIFS_KEY = ['notifications'] as const;

export const fetchNotifications = () => api<NotificationsList>('GET', '/api/notifications');

export const dismissNotifications = (body: { ids?: string[]; all?: boolean }) =>
  api<{ ok: boolean }>('POST', '/api/notifications/dismiss', body);
