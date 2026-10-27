/** Settings schema for W12 — keep in sync with `settings_schema.json` / SETTINGS_SPEC (Phase 1f). */

export type SettingsControl =
  | 'text'
  | 'textarea'
  | 'email'
  | 'tel'
  | 'url'
  | 'number'
  | 'select'
  | 'segmented'
  | 'switch'
  | 'slider'
  | 'button'
  | 'info'
  | 'html'
  | 'list'
  | 'table'
  | 'readonly';

export type SettingsField = {
  id: string;
  label: string;
  control: SettingsControl;
  default?: unknown;
  help?: string | null;
  scope?: string;
  options?: { value: string; label: string }[];
  validation?: Record<string, unknown>;
  admin_only?: boolean;
};

export type SettingsSub = {
  id: string;
  path: string;
  title: string;
  fields?: SettingsField[];
};

export type SettingsSection = {
  id: string;
  path: string;
  title: string;
  admin_only?: boolean;
  subs?: SettingsSub[];
  fields?: SettingsField[];
};

export const SECTION_ORDER = [
  'preferences',
  'folders',
  'identity',
  'responses',
  'filters',
  'vacation',
  'provider',
  'security',
  'users',
  'branches',
  'mailboxes',
] as const;

export const SECTION_TITLES: Record<string, string> = {
  preferences: 'Nastavenia',
  folders: 'Priečinky',
  identity: 'Identity',
  responses: 'Odpovede',
  filters: 'Filtre',
  vacation: 'Mimo kancelárie',
  provider: 'Nastavenia e-mail schránky',
  security: 'Bezpečnosť',
  users: 'Používatelia a role',
  branches: 'Pobočky a osoby',
  mailboxes: 'Schránky',
};
