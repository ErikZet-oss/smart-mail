import { api, apiForm } from '../../lib/api';

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
  api<Record<string, unknown>>('PUT', `/api/settings/identities/${id}`, body);

export type SignatureContext = {
  mailbox_kind: string;
  account_kind: string;
  branch_managed: boolean;
  preview_html: string;
  branch_id: string | null;
};

export type SignatureImageRecord = {
  id: string;
  cid: string;
  preview_url: string;
};

export const fetchSignatureContext = (mailbox = 'default') =>
  api<SignatureContext>('GET', `/api/settings/mailboxes/${encodeURIComponent(mailbox)}/signature-context`);

export const fetchSignaturePresets = () =>
  api<{ karta: Record<string, string>; text: Record<string, string> }>('GET', '/api/settings/signature-presets');

export const signRemotePreviews = (urls: string[]) =>
  api<{ previews: Record<string, string> }>(
    'POST',
    '/api/settings/signature-remote-previews',
    { urls },
    { global: false },
  );

export const uploadIdentityImage = (id: string, file: File) => {
  const body = new FormData();
  body.append('file', file);
  return apiForm<SignatureImageRecord>('POST', `/api/settings/identities/${id}/signature-images`, body);
};

export const uploadBranchImage = (id: string, file: File) => {
  const body = new FormData();
  body.append('file', file);
  return apiForm<SignatureImageRecord>('POST', `/api/settings/admin/branches/${id}/signature-images`, body);
};

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

/** Settings 09 „Dvojstupňové overenie“ (#77). */
export type TwoFactorStatus = { available: boolean; enabled: boolean; required: boolean; backup_codes_left: number };
export const fetchTwoFactor = () => api<TwoFactorStatus>('GET', '/api/settings/security/2fa');
export const startTwoFactor = () =>
  api<{ secret: string; otpauth_uri: string; backup_codes: string[] }>('POST', '/api/settings/security/2fa/start', {});
export const confirmTwoFactor = (code: string) =>
  api<{ enabled: boolean }>('POST', '/api/settings/security/2fa/confirm', { code });
export const disableTwoFactor = () => api<{ enabled: boolean }>('POST', '/api/settings/security/2fa/disable', {});

export const fetchAdminBranches = () => api<Record<string, unknown>[]>('GET', '/api/settings/admin/branches');
export const saveBranch = (id: string, body: Record<string, unknown>) =>
  api<Record<string, unknown>>('PUT', `/api/settings/admin/branches/${id}`, body);
export const createBranch = (body: Record<string, unknown>) => api('POST', '/api/settings/admin/branches', body);
export const savePersonAdmin = (id: string, body: Record<string, unknown>) =>
  api('PUT', `/api/settings/admin/people/${id}`, body);
export const addPersonAdmin = (branchId: string, body: Record<string, unknown>) =>
  api('POST', `/api/settings/admin/branches/${branchId}/people`, body);
export const fetchAdminMailboxes = () => api<Record<string, unknown>[]>('GET', '/api/settings/admin/mailboxes');
export const saveMailboxAdmin = (id: string, body: Record<string, unknown>) =>
  api('PUT', `/api/settings/admin/mailboxes/${id}`, body);

// ----- Settings 10/11 accounts, branches, persons (#33) -----

export type RoleId = 'admin' | 'sales' | 'warehouse' | 'accounting' | 'viewer';
export const ROLES: RoleId[] = ['admin', 'sales', 'warehouse', 'accounting', 'viewer'];

export type AdminUser = {
  id: string;
  email: string;
  kind: 'personal' | 'branch';
  active: boolean;
  last_login_at: string | null;
  branch_id: string | null;
  branch_name: string | null;
  persons_count?: number | null;
  require_2fa?: boolean;
  totp_enabled?: boolean;
  person: { id: string; first_name: string; last_name: string; role: RoleId; active: boolean } | null;
};

export type MailboxAccessRow = { mailbox_id: string; email: string; read: boolean; send: boolean; own: boolean };
export const fetchMailboxAccess = (id: string) =>
  api<MailboxAccessRow[]>('GET', `/api/settings/admin/users/${id}/mailbox-access`);
export const saveMailboxAccess = (id: string, body: { mailbox_id: string; read: boolean; send: boolean }[]) =>
  api<MailboxAccessRow[]>('PUT', `/api/settings/admin/users/${id}/mailbox-access`, body);
export const verifyUserLogin = (id: string, password: string) =>
  api<{ result: 'ok' }>('POST', `/api/settings/admin/users/${id}/verify`, { password });
export const resetUserTwoFactor = (id: string) =>
  api<AdminUser>('POST', `/api/settings/admin/users/${id}/reset-2fa`, {});
export const logoutUserEverywhere = (id: string) =>
  api<{ revoked_sessions: number }>('POST', `/api/settings/admin/users/${id}/logout-all`, {});

export type AdminPerson = {
  id: string;
  first_name: string;
  last_name: string;
  function: string | null;
  role: RoleId;
  is_manager: boolean;
  active: boolean;
  phone: string | null;
  mobile: string | null;
  personal_email: string | null;
  photo_url?: string | null;
  cover_branch_ids?: string[];
};

/** W12-11b „Osobné účty“ (#71): the person of a personal login and the branch used for its signature. */
export type PersonalPerson = AdminPerson & { login_email: string; branch_id: string | null };

export const deleteBranch = (id: string) => api('DELETE', `/api/settings/admin/branches/${id}`);
export type BranchFolder = { id: string; name: string; mailbox_email: string };
export const fetchBranchFolders = () => api<BranchFolder[]>('GET', '/api/settings/admin/branch-folders');

async function uploadImage<T>(url: string, file: File): Promise<T> {
  const body = new FormData();
  body.append('file', file);
  return apiForm<T>('POST', url, body);
}
export const uploadBranchLogo = (id: string, file: File) =>
  uploadImage<{ logo_url: string }>(`/api/settings/admin/branches/${id}/logo`, file);
export const removeBranchLogo = (id: string) => api('DELETE', `/api/settings/admin/branches/${id}/logo`);
export const uploadPersonPhoto = (id: string, file: File) =>
  uploadImage<{ photo_url: string }>(`/api/settings/admin/people/${id}/photo`, file);
export const removePersonPhoto = (id: string) => api('DELETE', `/api/settings/admin/people/${id}/photo`);

export const fetchPersonalPeople = () => api<PersonalPerson[]>('GET', '/api/settings/admin/personal-people');

export type BranchLogin = { id: string; email: string; kind: 'personal' | 'branch'; linked: boolean };

export const fetchUsers = () => api<AdminUser[]>('GET', '/api/settings/admin/users');
export const createUser = (body: {
  email: string;
  kind: 'personal' | 'branch';
  branch_id?: string | null;
  first_name?: string;
  last_name?: string;
  role?: RoleId;
}) => api<AdminUser>('POST', '/api/settings/admin/users', body);
export const patchUser = (
  id: string,
  body: {
    active?: boolean;
    kind?: 'personal' | 'branch';
    branch_id?: string | null;
    role?: RoleId;
    require_2fa?: boolean;
  },
) => api<AdminUser>('PATCH', `/api/settings/admin/users/${id}`, body);
export const deletePersonAdmin = (id: string) =>
  api<{ id: string; result: 'deleted' | 'deactivated' }>('DELETE', `/api/settings/admin/people/${id}`);
export const linkBranchLogin = (branchId: string) =>
  api<AdminUser>('POST', `/api/settings/admin/branches/${branchId}/link-login`, {});
