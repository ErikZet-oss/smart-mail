import { api } from '../../lib/api';

export type SearchScope = 'current' | 'subfolders' | 'all';
export type SearchField = 'subject' | 'from' | 'to' | 'cc' | 'body' | 'full';

export type MessageHit = {
  id: string;
  folder_id: string;
  mailbox_id: string;
  subject: string | null;
  from_name: string | null;
  from_email: string | null;
  preview: string | null;
  received_at: string | null;
  rank: number;
};

export type SearchResult = {
  q: string;
  scope: string;
  fields: string[];
  total: number;
  messages: MessageHit[];
  oldest_downloaded_at: string | null;
};

export type SearchParams = {
  q: string;
  scope?: SearchScope;
  fields?: SearchField[];
  folder_id?: string;
  mailbox?: string;
  limit?: number;
  offset?: number;
};

export function searchKey(params: SearchParams) {
  return ['search', params] as const;
}

export function runSearch(params: SearchParams) {
  const qs = new URLSearchParams();
  qs.set('q', params.q);
  if (params.scope) qs.set('scope', params.scope);
  if (params.folder_id) qs.set('folder_id', params.folder_id);
  if (params.mailbox) qs.set('mailbox', params.mailbox);
  if (params.limit) qs.set('limit', String(params.limit));
  if (params.offset) qs.set('offset', String(params.offset));
  for (const f of params.fields ?? ['full']) qs.append('fields', f);
  return api<SearchResult>('GET', `/api/search?${qs.toString()}`);
}
