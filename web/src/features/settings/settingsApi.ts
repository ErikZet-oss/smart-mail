import { api } from '../../lib/api';

export type NavSection = {
  id: string;
  path: string;
  title: string;
  subs: { id: string; path: string; title: string }[];
};

export const fetchSettingsNav = () => api<{ sections: NavSection[] }>('GET', '/api/settings/nav');

export const fetchPreferences = () =>
  api<{
    ui: Record<string, unknown>;
    list: Record<string, unknown>;
    reading: Record<string, unknown>;
    composing: Record<string, unknown>;
    shortcuts: Record<string, unknown>;
  }>('GET', '/api/settings/preferences');

export const savePreferences = (body: Record<string, unknown>) => api('PUT', '/api/settings/preferences', body);

export const fetchProfile = () => api<Record<string, unknown>>('GET', '/api/settings/profile');
export const saveProfile = (body: Record<string, unknown>) => api('PUT', '/api/settings/profile', body);

export const fetchIdentities = (mailbox = 'default') =>
  api<Record<string, unknown>[]>('GET', `/api/settings/mailboxes/${encodeURIComponent(mailbox)}/identities`);

export const saveIdentity = (id: string, body: Record<string, unknown>) =>
  api('PUT', `/api/settings/identities/${id}`, body);

export const fetchResponses = () => api<Record<string, unknown>[]>('GET', '/api/settings/responses');
export const createResponse = (body: Record<string, unknown>) => api('POST', '/api/settings/responses', body);
export const saveResponse = (id: string, body: Record<string, unknown>) =>
  api('PUT', `/api/settings/responses/${id}`, body);
export const deleteResponse = (id: string) => api('DELETE', `/api/settings/responses/${id}`);

export const fetchFilters = (mailbox = 'default') =>
  api<{
    rules: Record<string, unknown>[];
    script_name?: string;
    has_backup?: boolean;
    help?: string;
    mailbox_scope?: string;
    sieve_unavailable?: boolean;
    sieve_message?: string;
  }>('GET', `/api/settings/mailboxes/${encodeURIComponent(mailbox)}/filters`);
export const saveFilters = (mailbox: string, rules: unknown[]) =>
  api('PUT', `/api/settings/mailboxes/${encodeURIComponent(mailbox)}/filters`, { rules });

export const fetchVacation = (mailbox = 'default') =>
  api<Record<string, unknown>>('GET', `/api/settings/mailboxes/${encodeURIComponent(mailbox)}/vacation`);
export const saveVacation = (mailbox: string, body: Record<string, unknown>) =>
  api('PUT', `/api/settings/mailboxes/${encodeURIComponent(mailbox)}/vacation`, body);

export const restoreSieve = (mailbox = 'default') =>
  api<Record<string, unknown>>('POST', `/api/settings/mailboxes/${encodeURIComponent(mailbox)}/sieve/restore`);

export const fetchProvider = (mailbox = 'default') =>
  api<Record<string, unknown>>('GET', `/api/settings/mailboxes/${encodeURIComponent(mailbox)}/provider`);

export const fetchSessions = () => api<Record<string, unknown>[]>('GET', '/api/settings/security/sessions');
export const revokeSession = (id: string) => api('POST', `/api/settings/security/sessions/${id}/revoke`);

export const fetchAdminUsers = () => api<Record<string, unknown>[]>('GET', '/api/settings/admin/users');
export const fetchAdminBranches = () => api<Record<string, unknown>[]>('GET', '/api/settings/admin/branches');
export const saveBranch = (id: string, body: Record<string, unknown>) =>
  api('PUT', `/api/settings/admin/branches/${id}`, body);
export const createBranch = (body: Record<string, unknown>) => api('POST', '/api/settings/admin/branches', body);
export const savePersonAdmin = (id: string, body: Record<string, unknown>) =>
  api('PUT', `/api/settings/admin/people/${id}`, body);
export const addPersonAdmin = (branchId: string, body: Record<string, unknown>) =>
  api('POST', `/api/settings/admin/branches/${branchId}/people`, body);
export const fetchAdminMailboxes = () => api<Record<string, unknown>[]>('GET', '/api/settings/admin/mailboxes');
export const saveMailboxAdmin = (id: string, body: Record<string, unknown>) =>
  api('PUT', `/api/settings/admin/mailboxes/${id}`, body);
