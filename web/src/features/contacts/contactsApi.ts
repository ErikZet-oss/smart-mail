import { ApiError, api } from '../../lib/api';

export type AddressBook = { id: string; kind: string; name: string };
export type ContactGroup = { id: string; address_book_id: string; name: string };
export type Contact = {
  id: string;
  address_book_id: string;
  display_name: string;
  first_name: string | null;
  last_name: string | null;
  organization: string | null;
  notes: string | null;
  emails: { email: string; type?: string }[];
  phones: { number: string; type?: string }[];
  group_ids: string[];
};
export type ContactIn = {
  display_name: string;
  first_name?: string | null;
  last_name?: string | null;
  organization?: string | null;
  notes?: string | null;
  emails?: { email: string; type?: string }[];
  phones?: { number: string; type?: string }[];
  group_ids?: string[];
};
export type ImportStats = { created: number; merged: number; skipped: number };

export const booksKey = ['contacts', 'books'] as const;
export const contactsKey = (bookId: string, q = '') => ['contacts', bookId, q] as const;
export const groupsKey = (bookId: string) => ['contacts', 'groups', bookId] as const;

export const fetchBooks = () => api<AddressBook[]>('GET', '/api/contacts/books');

export function fetchContacts(bookId: string, q?: string) {
  const qs = q?.trim() ? `?q=${encodeURIComponent(q.trim())}` : '';
  return api<Contact[]>('GET', `/api/contacts/books/${bookId}/contacts${qs}`);
}

export const fetchGroups = (bookId: string) => api<ContactGroup[]>('GET', `/api/contacts/books/${bookId}/groups`);

export const createContact = (bookId: string, body: ContactIn) =>
  api<Contact>('POST', `/api/contacts/books/${bookId}/contacts`, body);

export const updateContact = (contactId: string, body: ContactIn) =>
  api<Contact>('PATCH', `/api/contacts/contacts/${contactId}`, body);

export const deleteContact = (contactId: string) => api<undefined>('DELETE', `/api/contacts/contacts/${contactId}`);

export const createGroup = (bookId: string, name: string) =>
  api<ContactGroup>('POST', `/api/contacts/books/${bookId}/groups`, { name });

export async function importVcard(bookId: string, file: File, onDuplicate: 'merge' | 'skip') {
  const form = new FormData();
  form.append('file', file);
  form.append('on_duplicate', onDuplicate);
  const csrf = document.cookie
    .split('; ')
    .find((c) => c.startsWith('sm_csrf='))
    ?.split('=')[1];
  const response = await fetch(`/api/contacts/books/${bookId}/import`, {
    method: 'POST',
    body: form,
    credentials: 'same-origin',
    headers: csrf ? { 'X-CSRF-Token': decodeURIComponent(csrf) } : undefined,
  });
  if (!response.ok) {
    let detail: { code: string; message?: string } = { code: 'http_error' };
    try {
      const body = (await response.json()) as { detail?: { code: string; message?: string } };
      if (body.detail?.code) detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as ImportStats;
}

export const exportVcardUrl = (bookId: string) => `/api/contacts/books/${bookId}/export`;

export function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const first = parts[0];
  const second = parts[1];
  if (!first) return '?';
  if (!second) return first.slice(0, 2).toUpperCase();
  return `${first[0] ?? ''}${second[0] ?? ''}`.toUpperCase();
}
