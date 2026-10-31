import { api, apiBlob, apiForm } from '../../lib/api';

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
  has_signature?: boolean;
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

// 17d Štýl a znalosti (admin, Phase 2e)
export type KnowledgeCardOut = {
  id: string;
  title: string;
  body: string;
  valid_until: string | null;
  tags: string[];
  enabled: boolean;
  expired: boolean;
  updated_at: string | null;
};
export type KnowledgeCardIn = {
  title: string;
  body: string;
  valid_until: string | null;
  tags: string[];
  enabled: boolean;
};

export const knowledgeKey = ['settings', 'ai', 'knowledge'] as const;
export const styleGuideKey = ['settings', 'ai', 'style-guide'] as const;

export const fetchStyleGuide = () =>
  api<{ body: string; updated_at: string | null }>('GET', '/api/settings/ai/style-guide');
export const saveStyleGuide = (body: string) =>
  api<{ body: string; updated_at: string | null }>('PUT', '/api/settings/ai/style-guide', { body });
export const fetchKnowledge = () => api<KnowledgeCardOut[]>('GET', '/api/settings/ai/knowledge');
export const createKnowledge = (card: KnowledgeCardIn) =>
  api<KnowledgeCardOut>('POST', '/api/settings/ai/knowledge', card);
export const updateKnowledge = (id: string, card: KnowledgeCardIn) =>
  api<KnowledgeCardOut>('PUT', `/api/settings/ai/knowledge/${id}`, card);
export const deleteKnowledge = (id: string) => api<{ status: string }>('DELETE', `/api/settings/ai/knowledge/${id}`);

// 17e Pravidlá (admin, Phase 2e)
export type StructuredRule = Record<string, unknown>;
export type AiRuleOut = {
  id: string;
  nl_text: string;
  description: string;
  enabled: boolean;
  last_used_at: string | null;
  created_by: string | null;
};
export type RuleTestOut = {
  checked: number;
  matches: { id: string; subject: string | null; from_email: string | null; received_at: string | null }[];
};

export const rulesKey = ['settings', 'ai', 'rules'] as const;
export const fetchRules = () => api<AiRuleOut[]>('GET', '/api/settings/ai/rules');
export const previewRule = (nl_text: string) =>
  api<{ structured: StructuredRule; description: string }>('POST', '/api/settings/ai/rules/preview', { nl_text });
export const createRule = (nl_text: string, structured: StructuredRule) =>
  api<AiRuleOut>('POST', '/api/settings/ai/rules', { nl_text, structured });
export const toggleRule = (id: string, enabled: boolean) =>
  api<AiRuleOut>('PATCH', `/api/settings/ai/rules/${id}`, { enabled });
export const deleteRule = (id: string) => api<{ status: string }>('DELETE', `/api/settings/ai/rules/${id}`);
export const testRule = (structured: StructuredRule) =>
  api<RuleTestOut>('POST', '/api/settings/ai/rules/test', { structured });

// 07 Personal style profile (each person, opt-in, Phase 2e)
export type StyleProfile = { opt_in: boolean; text: string; generated_at: string | null; source_count: number };
export const styleProfileKey = ['settings', 'ai', 'style-profile'] as const;
export const fetchStyleProfile = () => api<StyleProfile>('GET', '/api/settings/ai/style-profile');
export const saveStyleProfile = (body: { opt_in: boolean; text: string }) =>
  api<StyleProfile>('PUT', '/api/settings/ai/style-profile', body);
export const generateStyleProfile = () => api<StyleProfile>('POST', '/api/settings/ai/style-profile/generate', {});

// 17f Tieňový režim, spotreba a presnosť (admin, Phase 2f)
export type AiUsage = {
  days: { date: string; cost_usd: string; runs: number }[];
  total_cost_usd: string;
  budget_usd: string;
  cost_by_purpose: Record<string, string>;
  suggestions: {
    total: number;
    shadow: number;
    pending: number;
    approved: number;
    approved_unedited: number;
    rejected: number;
    approved_unedited_pct: number | null;
  };
  reject_reasons: Record<string, number>;
  categories: Record<string, number>;
  /** Last `make eval --save` on the server (aggregates only, #116). */
  eval: {
    run_at: string;
    mode: 'stored' | 'live';
    total: number;
    accuracy: string | null;
    language_accuracy: string | null;
    gate: string;
    passed: boolean;
    too_small: boolean;
    confusion: { label: string; predicted: string; count: number }[];
  } | null;
};
export const usageKey = ['settings', 'ai', 'usage'] as const;
export const shadowKey = ['settings', 'ai', 'shadow'] as const;
export const fetchUsage = () => api<AiUsage>('GET', '/api/settings/ai/usage');
export const fetchShadow = () => api<{ replies: boolean }>('GET', '/api/settings/ai/shadow');
export const saveShadow = (replies: boolean) =>
  api<{ replies: boolean }>('PUT', '/api/settings/ai/shadow', { replies });

/** 07 Samostatnosť per login (D8) and the 17b read-only overview (#116). */
export type AutonomyAction = { id: string; level: number; default: number; max: number; hard: boolean };
export type AccountAutonomy = {
  account_id: string;
  email: string;
  kind: string;
  levels: Record<string, number>;
  customized: boolean;
};
export const autonomyKey = ['settings', 'ai', 'autonomy'] as const;
export const autonomyOverviewKey = ['settings', 'ai', 'autonomy', 'overview'] as const;
export const fetchAutonomy = () => api<{ actions: AutonomyAction[] }>('GET', '/api/settings/ai/autonomy');
export const saveAutonomy = (levels: Record<string, number>) =>
  api<{ actions: AutonomyAction[] }>('PUT', '/api/settings/ai/autonomy', { levels });
export const fetchAutonomyOverview = () => api<AccountAutonomy[]>('GET', '/api/settings/ai/autonomy/overview');

/** 17a Poskytovateľ a rozpočet (#116): budget from env until an admin saves one (1–500 USD). */
export type AiLimits = {
  provider: string;
  region: string | null;
  models: { purpose: string; model: string | null }[];
  daily_budget_usd: string;
  budget_source: 'env' | 'app';
  env_budget_usd: string;
  alert_pct: number;
  on_exhausted: 'rules_only' | 'ai_off';
  retention_days: 30 | 90 | 365;
};
export type AiLimitsIn = {
  daily_budget_usd: string | null;
  alert_pct: number;
  on_exhausted: AiLimits['on_exhausted'];
  retention_days: AiLimits['retention_days'];
};
export const limitsKey = ['settings', 'ai', 'limits'] as const;
export const fetchLimits = () => api<AiLimits>('GET', '/api/settings/ai/limits');
export const saveLimits = (body: AiLimitsIn) => api<AiLimits>('PUT', '/api/settings/ai/limits', body);

/** 17c Kategórie (#116): built-ins (description, on/off) + max 15 custom; descriptions feed the classify prompt. */
export type CategoryColor = 'warning' | 'success' | 'danger' | 'info' | 'brand' | 'neutral';
export type CategoryRow = {
  id: string;
  label: string;
  description: string;
  default_description: string | null;
  color: CategoryColor;
  enabled: boolean;
  builtin: boolean;
  locked: boolean;
  count_30d: number;
};
export type CategoryRowIn = {
  id: string | null;
  label: string | null;
  description: string;
  color: CategoryColor;
  enabled: boolean;
};
export const categoriesKey = ['settings', 'ai', 'categories'] as const;
export const fetchCategories = () => api<CategoryRow[]>('GET', '/api/settings/ai/categories');
export const saveCategories = (categories: CategoryRowIn[]) =>
  api<CategoryRow[]>('PUT', '/api/settings/ai/categories', { categories });

/** 17f eval label file (Erik's answer B on #129): admin + re-auth; the app keeps only aggregates. */
export const downloadEvalSample = () =>
  api<{ filename: string; csv: string; rows: number }>('POST', '/api/settings/ai/eval/sample', {});
export const uploadEvalLabels = (csv: string) =>
  api<NonNullable<AiUsage['eval']>>('POST', '/api/settings/ai/eval/upload', { csv });

/** #139 „Pečiatka“ (branch) / „Podpis“ (person): transparent PNG, admin + re-auth; preview only for admins. */
export const stampUrl = (branchId: string) => `/api/settings/admin/branches/${branchId}/stamp`;
export const signatureUrl = (personId: string) => `/api/settings/admin/people/${personId}/signature`;
export const uploadPrivateImage = (url: string, file: File) => uploadImage<Record<string, boolean>>(url, file);
export const removePrivateImage = (url: string) => api<Record<string, boolean>>('DELETE', url);

/** 13a / 13e Money S4 (Phase 3b, admin). */
export type MoneyEntityState = {
  entity: 'companies' | 'persons' | 'codebooks';
  last_run_at: string | null;
  last_full_at: string | null;
  status: 'ok' | 'error' | null;
  error: string | null;
  rows: number;
};
export type MoneyStatus = {
  enabled: boolean;
  reachable: boolean;
  error: string | null;
  backend: string | null;
  agenda: string | null;
  bridge_version: string | null;
  money_version: string | null;
  latency_ms: number | null;
  writes_enabled: boolean;
  entities: MoneyEntityState[];
};
export type MoneySyncRun = {
  entity: MoneyEntityState['entity'];
  at: string;
  full: boolean;
  status: string;
  changed: number;
  deactivated: number;
  error: string | null;
  duration_ms: number;
};
export type MoneySync = { interval_min: number; running: boolean; history: MoneySyncRun[] };

export const moneyStatusKey = ['settings', 'money', 'status'] as const;
export const moneySyncKey = ['settings', 'money', 'sync'] as const;
export const fetchMoneyStatus = () => api<MoneyStatus>('GET', '/api/settings/money/status');
export const fetchMoneySync = () => api<MoneySync>('GET', '/api/settings/money/sync');
export const saveMoneyInterval = (interval_min: number) =>
  api<MoneySync>('PUT', '/api/settings/money/sync', { interval_min });
export const startMoneySync = () => api<{ queued: boolean }>('POST', '/api/settings/money/sync-now');

/** 13b Tlačové zostavy (Phase 3d): report id (GUID or config id) per document kind and language; empty → SK. */
export type MoneyReports = Record<'invoice' | 'proforma', Record<'sk' | 'en' | 'de', string>>;
export const moneyReportsKey = ['settings', 'money', 'reports'] as const;
export const fetchMoneyReports = () => api<MoneyReports>('GET', '/api/settings/money/reports');
export const saveMoneyReports = (body: MoneyReports) => api<MoneyReports>('PUT', '/api/settings/money/reports', body);
export const testMoneyReport = (kind: string, lang: string, number: string) =>
  apiBlob(
    'GET',
    `/api/settings/money/reports/test?kind=${encodeURIComponent(kind)}&lang=${encodeURIComponent(lang)}&number=${encodeURIComponent(number)}`,
  );

/** 11e Money (pobočka): centre + own print reports (SK) per branch (#174). */
export type BranchMoney = {
  id: string;
  name: string;
  centre_id: string | null;
  centre_missing: boolean;
  reports: Record<'invoice' | 'proforma', string>;
};
export type BranchMoneyList = {
  centres: { id: string; code: string | null; name: string | null }[];
  branches: BranchMoney[];
};
export const branchMoneyKey = ['settings', 'money', 'branches'] as const;
export const fetchBranchMoney = () => api<BranchMoneyList>('GET', '/api/settings/money/branches');
export const saveBranchMoney = (id: string, body: { centre_id: string | null; reports: Record<string, string> }) =>
  api<BranchMoney>('PUT', `/api/settings/money/branches/${encodeURIComponent(id)}`, body);
export const testBranchReport = (id: string, kind: string, number: string) =>
  apiBlob(
    'GET',
    `/api/settings/money/branches/${encodeURIComponent(id)}/test?kind=${encodeURIComponent(kind)}&number=${encodeURIComponent(number)}`,
  );

/** 13a „Zápisy do Money povolené“ ⚠ and 13d Aktivity (Phase 3f). */
export type MoneyWrites = { enabled: boolean; key_configured: boolean };
export type MoneyActivities = {
  enabled: boolean;
  type_email: string | null;
  type_reminder: string | null;
  writes_enabled: boolean;
  types: { id: string; code: string | null; name: string | null }[];
  failed: { draft_id: string; at: string; error: string | null; kind: string | null; invoices: string[] }[];
};
export const moneyWritesKey = ['settings', 'money', 'writes'] as const;
export const moneyActivitiesKey = ['settings', 'money', 'activities'] as const;
export const fetchMoneyWrites = () => api<MoneyWrites>('GET', '/api/settings/money/writes');
export const saveMoneyWrites = (enabled: boolean) => api<MoneyWrites>('PUT', '/api/settings/money/writes', { enabled });
export const fetchMoneyActivities = () => api<MoneyActivities>('GET', '/api/settings/money/activities');
export const saveMoneyActivities = (body: {
  enabled: boolean;
  type_email: string | null;
  type_reminder: string | null;
}) => api<MoneyActivities>('PUT', '/api/settings/money/activities', body);
export const retryMoneyActivity = (draftId: string) =>
  api<{ queued: boolean }>('POST', `/api/settings/money/activities/${encodeURIComponent(draftId)}/retry`);
