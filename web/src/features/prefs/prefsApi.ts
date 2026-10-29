import { api } from '../../lib/api';

export type ListPrefs = {
  sort: 'date_received' | 'date_sent' | 'subject' | 'from' | 'size';
  sort_dir: 'asc' | 'desc';
  mode: 'list' | 'conversations';
  density: 'compact' | 'comfortable';
  page_size: number;
  show_ai_summary: boolean;
  mark_read: 'immediate' | 'delay3' | 'never';
  after_delete: 'next' | 'previous' | 'list';
};

export type UiPrefs = {
  theme: 'light' | 'dark' | 'system';
  classic: boolean;
  remote_images: 'never' | 'known' | 'always';
  prefer_html: boolean;
};

export type Prefs = { list: ListPrefs; ui: UiPrefs; shortcuts?: { enabled: boolean } };

export const PREFS_KEY = ['mail', 'prefs'] as const;

export const fetchPrefs = () => api<Prefs>('GET', '/api/mail/prefs', undefined, { global: false });

export const savePrefs = (body: { list?: Partial<ListPrefs>; ui?: Partial<UiPrefs> }) =>
  api<Prefs>('PUT', '/api/mail/prefs', body, { global: false });
