import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { Button } from '../../components/Button';
import { Banner } from '../../components/Banner';
import { AppShell } from '../../components/shell/AppShell';
import { useToasts } from '../../components/toastContext';
import { ApiError } from '../../lib/api';
import { MOBILE_QUERY, useMediaQuery } from '../../lib/useMediaQuery';
import { fetchMe } from '../auth/authApi';
import { SettingsFieldControl } from './Field';
import { HtmlSignatureEditor } from './HtmlSignatureEditor';
import { MobileSettingsIndex } from './MobileSettingsIndex';
import { SECTION_TITLES, type SettingsField } from './schema';
import {
  addPersonAdmin,
  createResponse,
  deleteResponse,
  fetchAdminBranches,
  fetchAdminMailboxes,
  fetchAdminUsers,
  fetchFilters,
  fetchIdentities,
  fetchPreferences,
  fetchProfile,
  fetchProvider,
  fetchResponses,
  fetchSessions,
  fetchSettingsNav,
  fetchVacation,
  restoreSieve,
  revokeSession,
  saveBranch,
  saveFilters,
  saveIdentity,
  saveMailboxAdmin,
  savePreferences,
  saveProfile,
  saveVacation,
} from './settingsApi';

type FilterRuleDraft = {
  id?: string;
  name?: string;
  enabled?: boolean;
  match?: string;
  conditions?: { field: string; op: string; value: string; header_name?: string }[];
  actions?: { type: string; value: string }[];
  editable?: boolean;
  raw?: string | null;
  kind?: string;
  readonly_label?: string | null;
};

const PREF_FIELDS_UI: SettingsField[] = [
  {
    id: 'theme',
    label: 'Vzhľad',
    control: 'segmented',
    default: 'system',
    options: [
      { value: 'light', label: 'Svetlý' },
      { value: 'dark', label: 'Tmavý' },
      { value: 'system', label: 'Podľa systému' },
    ],
  },
  {
    id: 'classic',
    label: 'Klasické zobrazenie',
    control: 'switch',
    default: false,
    help: 'Skryje AI triedenie, zhrnutia a asistenta – vyzerá ako Roundcube.',
  },
];

const PREF_FIELDS_LIST: SettingsField[] = [
  {
    id: 'density',
    label: 'Hustota zoznamu',
    control: 'segmented',
    default: 'compact',
    options: [
      { value: 'compact', label: 'Kompaktná' },
      { value: 'comfortable', label: 'Pohodlná' },
    ],
  },
  {
    id: 'mode',
    label: 'Režim zoznamu',
    control: 'segmented',
    default: 'list',
    options: [
      { value: 'list', label: 'Zoznam' },
      { value: 'conversations', label: 'Konverzácie' },
    ],
  },
  {
    id: 'page_size',
    label: 'Počet správ na stránku',
    control: 'select',
    default: '50',
    options: [
      { value: '25', label: '25' },
      { value: '50', label: '50' },
      { value: '100', label: '100' },
      { value: '200', label: '200' },
    ],
  },
];

const PREF_FIELDS_COMPOSING: SettingsField[] = [
  {
    id: 'undo_send_seconds',
    label: 'Oneskorenie odoslania (Späť)',
    control: 'slider',
    default: 10,
    validation: { min: 0, max: 30, step: 5 },
    help: 'Počas tohto času môžete odoslanie zrušiť.',
  },
  { id: 'default_mdn', label: 'Potvrdenie o doručení predvolene', control: 'switch', default: false },
  { id: 'pre_send_check', label: 'Kontrola pred odoslaním', control: 'switch', default: true },
];

/** W12 / M9 Nastavenia — Phase 1f sections; mobile index per SETTINGS_SPEC §M9. */
export function ScreenW12() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { section, sub } = useParams();
  const mobile = useMediaQuery(MOBILE_QUERY);
  const me = useQuery({ queryKey: ['me'], queryFn: fetchMe, retry: false });
  const nav = useQuery({ queryKey: ['settings', 'nav'], queryFn: fetchSettingsNav });
  const activeSection = section ?? (mobile ? '' : 'preferences');
  const title =
    activeSection === 'identity' && sub === 'profile'
      ? t('settings.profile.title')
      : mobile && activeSection === 'preferences'
        ? t('settings.mobile.prefs')
        : activeSection
          ? (SECTION_TITLES[activeSection] ?? t('settings.title'))
          : t('settings.title');

  if (mobile && !activeSection) {
    return (
      <AppShell section="settings">
        <MobileSettingsIndex />
      </AppShell>
    );
  }

  if (mobile && activeSection) {
    return (
      <AppShell section="settings">
        <div className="flex h-full min-h-0 flex-col bg-bg-canvas" data-testid="mobile-settings-section">
          <header className="flex h-12 shrink-0 items-center gap-1 border-b border-border-default px-1">
            <button
              type="button"
              onClick={() => navigate('/settings')}
              aria-label={t('system.back')}
              className="flex size-11 items-center justify-center rounded-sm text-text-primary hover:bg-bg-subtle"
            >
              <ArrowLeft size={22} />
            </button>
            <h1 className="type-heading min-w-0 flex-1 truncate text-text-primary">{title}</h1>
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            <SectionBody section={activeSection} sub={sub} meRole={me.data?.person?.role} />
          </div>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell section="settings">
      <div className="flex h-full min-w-0 flex-1">
        <nav
          aria-label={t('settings.nav')}
          className="flex w-[220px] shrink-0 flex-col gap-0.5 overflow-y-auto border-r border-border-default bg-bg-subtle p-3"
        >
          <p className="type-label mb-2 px-2 text-text-tertiary">{t('settings.title')}</p>
          {(nav.data?.sections ?? []).map((s) => (
            <div key={s.id} className="mb-1">
              <Link
                to={`/settings/${s.path}${s.subs[0] ? `/${s.subs[0].path}` : ''}`}
                className={`type-body block rounded-sm px-2 py-1.5 ${
                  activeSection === s.path
                    ? 'bg-brand-primary-50 text-brand-primary-700'
                    : 'text-text-primary hover:bg-bg-muted'
                }`}
              >
                {s.title}
              </Link>
              {activeSection === s.path && s.subs.length > 0 ? (
                <ul className="ml-2 mt-0.5 border-l border-border-default pl-2">
                  {s.subs.map((subItem) => (
                    <li key={subItem.id}>
                      <Link
                        to={`/settings/${s.path}/${subItem.path}`}
                        className={`type-small block rounded-sm px-2 py-1 ${
                          sub === subItem.path
                            ? 'text-brand-primary-700'
                            : 'text-text-secondary hover:text-text-primary'
                        }`}
                      >
                        {subItem.title}
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ))}
        </nav>
        <main className="flex min-w-0 flex-1 flex-col bg-bg-canvas">
          <header className="flex h-14 shrink-0 items-center border-b border-border-default px-6">
            <h1 className="type-heading text-text-primary">
              {t('settings.title')} › {title}
            </h1>
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto p-6">
            <SectionBody section={activeSection || 'preferences'} sub={sub} meRole={me.data?.person?.role} />
          </div>
        </main>
      </div>
    </AppShell>
  );
}

function SectionBody({ section, sub, meRole }: { section: string; sub?: string; meRole?: string }) {
  if (section === 'preferences') return <PreferencesPanel sub={sub} />;
  if (section === 'identity' && sub === 'profile') return <ProfilePanel />;
  if (section === 'identity') return <IdentitiesPanel />;
  if (section === 'responses') return <ResponsesPanel />;
  if (section === 'filters') return <FiltersPanel />;
  if (section === 'vacation') return <VacationPanel />;
  if (section === 'provider') return <ProviderPanel />;
  if (section === 'security') return <SecurityPanel />;
  if (section === 'folders') return <FoldersHint />;
  if (section === 'users') return meRole === 'admin' ? <UsersPanel /> : <AdminOnly />;
  if (section === 'branches') return meRole === 'admin' ? <BranchesPanel sub={sub} /> : <AdminOnly />;
  if (section === 'mailboxes') return meRole === 'admin' ? <MailboxesPanel /> : <AdminOnly />;
  return <p className="type-body text-text-secondary">…</p>;
}

function AdminOnly() {
  const { t } = useTranslation();
  return <Banner kind="warning" message={t('settings.adminOnly')} />;
}

function FoldersHint() {
  const { t } = useTranslation();
  return <p className="type-body text-text-secondary">{t('settings.foldersHint')}</p>;
}

function PreferencesPanel({ sub }: { sub?: string }) {
  const { t } = useTranslation();
  const toasts = useToasts();
  const prefs = useQuery({ queryKey: ['settings', 'prefs'], queryFn: fetchPreferences });
  const [draft, setDraft] = useState<{
    ui?: Record<string, unknown>;
    list?: Record<string, unknown>;
    composing?: Record<string, unknown>;
  } | null>(null);
  const ui = draft?.ui ?? prefs.data?.ui ?? {};
  const list = draft?.list ?? {
    ...(prefs.data?.list ?? {}),
    page_size: String(prefs.data?.list?.page_size ?? 50),
  };
  const composing = draft?.composing ?? prefs.data?.composing ?? {};

  const save = useMutation({
    mutationFn: () =>
      savePreferences({
        ui,
        list: { ...list, page_size: Number(list.page_size ?? 50) },
        composing,
        reading: prefs.data?.reading ?? {},
        shortcuts: prefs.data?.shortcuts ?? {},
      }),
    onSuccess: () => toasts.success(t('settings.saved')),
  });

  const which = sub ?? 'ui';
  const mobile = useMediaQuery(MOBILE_QUERY);
  // M9: Vzhľad page also exposes Oneskorenie odoslania (SETTINGS_SPEC §M9 / 01d).
  const showMobileUndo = mobile && which === 'ui';
  const fields =
    which === 'mailbox-view' || which === 'list'
      ? PREF_FIELDS_LIST
      : which === 'composing'
        ? PREF_FIELDS_COMPOSING
        : PREF_FIELDS_UI;
  const state = which === 'mailbox-view' || which === 'list' ? list : which === 'composing' ? composing : ui;
  const patch = (value: Record<string, unknown>) => {
    if (which === 'mailbox-view' || which === 'list') setDraft({ ui, list: value, composing });
    else if (which === 'composing') setDraft({ ui, list, composing: value });
    else setDraft({ ui: value, list, composing });
  };
  const undoField = PREF_FIELDS_COMPOSING.find((f) => f.id === 'undo_send_seconds');

  return (
    <div className="flex max-w-xl flex-col gap-4">
      {fields.map((field) => (
        <SettingsFieldControl
          key={field.id}
          field={field}
          value={state[field.id]}
          onChange={(value) => patch({ ...state, [field.id]: value })}
        />
      ))}
      {showMobileUndo && undoField ? (
        <SettingsFieldControl
          key={undoField.id}
          field={undoField}
          value={composing[undoField.id]}
          onChange={(value) => setDraft({ ui, list, composing: { ...composing, [undoField.id]: value } })}
        />
      ) : null}
      <Button type="button" onClick={() => save.mutate()} disabled={save.isPending}>
        {t('settings.save')}
      </Button>
    </div>
  );
}

function ProfilePanel() {
  const { t } = useTranslation();
  const toasts = useToasts();
  const profile = useQuery({ queryKey: ['settings', 'profile'], queryFn: fetchProfile });
  const [draft, setDraft] = useState<Record<string, unknown> | null>(null);
  const form = draft ?? profile.data ?? {};
  const save = useMutation({
    mutationFn: () => saveProfile(form),
    onSuccess: () => toasts.success(t('settings.saved')),
  });
  if (!profile.data) return null;
  return (
    <div className="flex max-w-xl flex-col gap-4">
      {(['first_name', 'last_name', 'function', 'phone', 'mobile', 'personal_email'] as const).map((key) => (
        <label key={key} className="flex flex-col gap-1">
          <span className="type-label text-text-secondary">{t(`settings.profile.${camel(key)}`)}</span>
          <input
            className="type-body h-9 rounded-sm border border-border-default px-3"
            value={String(form[key] ?? '')}
            onChange={(event) => setDraft({ ...form, [key]: event.target.value })}
          />
        </label>
      ))}
      <div
        className="rounded-sm border border-border-default p-3"
        dangerouslySetInnerHTML={{ __html: String(form.signature_preview_html ?? '') }}
      />
      <Button type="button" onClick={() => save.mutate()} disabled={save.isPending}>
        {t('settings.save')}
      </Button>
    </div>
  );
}

function camel(key: string) {
  return key.replace(/_([a-z])/g, (_, c: string) => c.toUpperCase());
}

function IdentitiesPanel() {
  const { t } = useTranslation();
  const toasts = useToasts();
  const list = useQuery({ queryKey: ['settings', 'identities'], queryFn: () => fetchIdentities() });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Record<string, unknown> | null>(null);
  const server = (list.data ?? []).find((i) => String(i.id) === selectedId) ?? list.data?.[0];
  const form = draft && String(draft.id) === String(server?.id) ? draft : (server ?? null);
  const save = useMutation({
    mutationFn: async () => {
      if (!form?.id) return;
      await saveIdentity(String(form.id), form);
    },
    onSuccess: () => toasts.success(t('settings.saved')),
  });
  return (
    <div className="flex gap-6">
      <ul className="w-56 shrink-0">
        {(list.data ?? []).map((i) => (
          <li key={String(i.id)}>
            <button
              type="button"
              className={`type-body w-full rounded-sm px-2 py-1.5 text-left ${
                form && i.id === form.id ? 'bg-brand-primary-50' : 'hover:bg-bg-subtle'
              }`}
              onClick={() => {
                setSelectedId(String(i.id));
                setDraft(i);
              }}
            >
              {String(i.display_name)} &lt;{String(i.email)}&gt;
            </button>
          </li>
        ))}
      </ul>
      {form?.id ? (
        <div className="flex max-w-xl flex-1 flex-col gap-3">
          <label className="flex flex-col gap-1">
            <span className="type-label text-text-secondary">{t('settings.identity.displayName')}</span>
            <input
              className="type-body h-9 rounded-sm border border-border-default px-3"
              value={String(form.display_name ?? '')}
              onChange={(event) => setDraft({ ...form, display_name: event.target.value })}
            />
          </label>
          <HtmlSignatureEditor
            label={t('settings.identity.signature')}
            value={String((form.signature_html as Record<string, string> | undefined)?.sk ?? '')}
            onChange={(html) =>
              setDraft({
                ...form,
                signature_html: { ...((form.signature_html as object) ?? {}), sk: html },
              })
            }
          />
          <Button type="button" onClick={() => save.mutate()} disabled={save.isPending}>
            {t('settings.save')}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function ResponsesPanel() {
  const { t } = useTranslation();
  const toasts = useToasts();
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ['settings', 'responses'], queryFn: fetchResponses });
  const [name, setName] = useState('');
  const [body, setBody] = useState('<p></p>');
  const create = useMutation({
    mutationFn: () => createResponse({ name, language: 'sk', body_html: body, shared: false }),
    onSuccess: () => {
      toasts.success(t('settings.saved'));
      setName('');
      void qc.invalidateQueries({ queryKey: ['settings', 'responses'] });
    },
  });
  return (
    <div className="flex max-w-2xl flex-col gap-4">
      <ul className="flex flex-col gap-2">
        {(list.data ?? []).map((r) => (
          <li
            key={String(r.id)}
            className="flex items-center justify-between rounded-sm border border-border-default px-3 py-2"
          >
            <span className="type-body">{String(r.name)}</span>
            <Button
              type="button"
              variant="secondary"
              onClick={() =>
                void deleteResponse(String(r.id)).then(
                  () => void qc.invalidateQueries({ queryKey: ['settings', 'responses'] }),
                )
              }
            >
              {t('settings.responses.delete')}
            </Button>
          </li>
        ))}
      </ul>
      <input
        className="type-body h-9 rounded-sm border border-border-default px-3"
        placeholder={t('settings.responses.name')}
        value={name}
        onChange={(event) => setName(event.target.value)}
      />
      <HtmlSignatureEditor value={body} onChange={setBody} label={t('settings.responses.body')} />
      <Button type="button" onClick={() => create.mutate()} disabled={!name || create.isPending}>
        {t('settings.responses.create')}
      </Button>
    </div>
  );
}

function FiltersPanel() {
  const { t } = useTranslation();
  const toasts = useToasts();
  const qc = useQueryClient();
  const data = useQuery({ queryKey: ['settings', 'filters'], queryFn: () => fetchFilters() });
  const [draft, setDraft] = useState<FilterRuleDraft[] | null>(null);
  const rules = (draft ?? (data.data?.rules as FilterRuleDraft[] | undefined) ?? []) as FilterRuleDraft[];
  const patchRule = (index: number, patch: Partial<FilterRuleDraft>) => {
    const next = [...rules];
    const current = next[index] ?? {};
    // clearing raw forces recompile from conditions/actions on save
    next[index] = { ...current, ...patch, raw: patch.raw === undefined ? null : patch.raw };
    setDraft(next);
  };
  const sieveErrorMessage = (error: unknown) => {
    if (error instanceof ApiError && typeof error.detail.message === 'string') {
      return error.detail.message;
    }
    if (error instanceof ApiError && error.detail.code === 'read_only') {
      return t('settings.filters.readOnly');
    }
    if (error instanceof ApiError && error.detail.code === 'mailbox_send_forbidden') {
      return t('settings.filters.noSend');
    }
    return t('settings.sieveError');
  };
  const save = useMutation({
    mutationFn: () => saveFilters('default', rules),
    onSuccess: () => {
      toasts.success(t('settings.saved'));
      void qc.invalidateQueries({ queryKey: ['settings', 'filters'] });
      setDraft(null);
    },
    onError: (error) => toasts.error(sieveErrorMessage(error)),
  });
  const restore = useMutation({
    mutationFn: () => restoreSieve('default'),
    onSuccess: () => {
      toasts.success(t('settings.sieveRestored'));
      void qc.invalidateQueries({ queryKey: ['settings', 'filters'] });
      void qc.invalidateQueries({ queryKey: ['settings', 'vacation'] });
      setDraft(null);
    },
    onError: (error) => toasts.error(sieveErrorMessage(error)),
  });
  const scope = data.data?.mailbox_scope;
  const fieldOptions = [
    { value: 'from', label: t('settings.filters.fields.from') },
    { value: 'to', label: t('settings.filters.fields.to') },
    { value: 'cc', label: t('settings.filters.fields.cc') },
    { value: 'subject', label: t('settings.filters.fields.subject') },
    { value: 'body', label: t('settings.filters.fields.body') },
    { value: 'header', label: t('settings.filters.fields.header') },
    { value: 'size', label: t('settings.filters.fields.size') },
  ];
  return (
    <div className="flex max-w-2xl flex-col gap-4">
      <Banner kind="info" message={t('settings.filters.mailboxScope')} />
      <p className="type-small text-text-secondary">{t('settings.filtersHelp')}</p>
      <p className="type-small text-text-secondary">{t('settings.filters.notDefaults')}</p>
      {rules.map((rule, index) => {
        const editable = rule.editable !== false;
        const cond = rule.conditions?.[0] ?? { field: 'from', op: 'contains', value: '' };
        const action = rule.actions?.find((a) => a.type === 'fileinto') ?? rule.actions?.[0];
        return (
          <div key={String(rule.id ?? index)} className="rounded-sm border border-border-default p-3">
            {!editable ? (
              <p className="type-label mb-2 text-text-tertiary">{t('settings.filters.roundcubeReadonly')}</p>
            ) : null}
            <input
              className="type-body mb-2 h-9 w-full rounded-sm border border-border-default px-3"
              value={String(rule.name ?? '')}
              disabled={!editable}
              onChange={(event) => patchRule(index, { name: event.target.value })}
            />
            <label className="mb-2 flex items-center gap-2 type-small">
              <input
                type="checkbox"
                checked={Boolean(rule.enabled)}
                disabled={!editable}
                onChange={(event) => patchRule(index, { enabled: event.target.checked })}
              />
              {t('settings.filters.enabled')}
            </label>
            {editable ? (
              <div className="flex flex-col gap-2">
                <label className="flex flex-col gap-1">
                  <span className="type-label text-text-secondary">{t('settings.filters.conditionField')}</span>
                  <select
                    className="type-body h-9 rounded-sm border border-border-default px-3"
                    value={cond.field || 'from'}
                    onChange={(event) =>
                      patchRule(index, {
                        conditions: [
                          {
                            field: event.target.value,
                            op: cond.op || 'contains',
                            value: cond.value || '',
                            header_name: event.target.value === 'header' ? (cond.header_name ?? '') : undefined,
                          },
                        ],
                        match: rule.match || 'anyof',
                      })
                    }
                  >
                    {fieldOptions.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </label>
                {cond.field === 'header' ? (
                  <label className="flex flex-col gap-1">
                    <span className="type-label text-text-secondary">{t('settings.filters.headerName')}</span>
                    <input
                      className="type-body h-9 rounded-sm border border-border-default px-3"
                      value={String(cond.header_name ?? '')}
                      placeholder="X-Priority"
                      onChange={(event) =>
                        patchRule(index, {
                          conditions: [
                            {
                              field: 'header',
                              op: cond.op || 'contains',
                              value: cond.value || '',
                              header_name: event.target.value,
                            },
                          ],
                        })
                      }
                    />
                  </label>
                ) : null}
                <label className="flex flex-col gap-1">
                  <span className="type-label text-text-secondary">
                    {cond.field === 'from'
                      ? t('settings.filters.from')
                      : cond.field === 'size'
                        ? t('settings.filters.sizeKb')
                        : t('settings.filters.conditionValue')}
                  </span>
                  <input
                    className="type-body h-9 rounded-sm border border-border-default px-3"
                    value={String(cond.value ?? '')}
                    placeholder={cond.field === 'from' ? '@dodavatel.test' : ''}
                    onChange={(event) =>
                      patchRule(index, {
                        conditions: [
                          {
                            field: cond.field || 'from',
                            op: cond.op || 'contains',
                            value: event.target.value,
                            header_name: cond.header_name,
                          },
                        ],
                        match: rule.match || 'anyof',
                      })
                    }
                  />
                </label>
                <label className="flex flex-col gap-1">
                  <span className="type-label text-text-secondary">{t('settings.filters.fileinto')}</span>
                  <input
                    className="type-body h-9 rounded-sm border border-border-default px-3"
                    value={action?.type === 'fileinto' ? String(action.value ?? '') : ''}
                    placeholder="Dodávatelia"
                    onChange={(event) =>
                      patchRule(index, {
                        actions: [
                          { type: 'fileinto', value: event.target.value },
                          { type: 'stop', value: '' },
                        ],
                      })
                    }
                  />
                </label>
              </div>
            ) : (
              <pre className="type-mono max-h-40 overflow-auto rounded-sm bg-bg-subtle p-2 text-text-secondary">
                {String(rule.raw ?? '')}
              </pre>
            )}
          </div>
        );
      })}
      <Button
        type="button"
        variant="secondary"
        onClick={() =>
          setDraft([
            ...rules,
            {
              id: `new-${Date.now()}`,
              name: t('settings.filters.newName'),
              enabled: true,
              match: 'allof',
              conditions: [{ field: 'from', op: 'contains', value: '' }],
              actions: [
                { type: 'fileinto', value: 'Dodávatelia' },
                { type: 'stop', value: '' },
              ],
              editable: true,
              raw: null,
            },
          ])
        }
      >
        {t('settings.filters.add')}
      </Button>
      <div className="flex flex-wrap gap-2">
        <Button type="button" onClick={() => save.mutate()} disabled={save.isPending}>
          {t('settings.save')}
        </Button>
        {data.data?.has_backup ? (
          <Button type="button" variant="secondary" onClick={() => restore.mutate()} disabled={restore.isPending}>
            {t('settings.sieveRestore')}
          </Button>
        ) : null}
      </div>
      {scope ? (
        <p className="type-caption text-text-tertiary">
          {t('settings.filters.scopeKind')}: {scope}
        </p>
      ) : null}
    </div>
  );
}

function VacationPanel() {
  const { t } = useTranslation();
  const toasts = useToasts();
  const qc = useQueryClient();
  const data = useQuery({ queryKey: ['settings', 'vacation'], queryFn: () => fetchVacation() });
  const [draft, setDraft] = useState<Record<string, unknown> | null>(null);
  const [lang, setLang] = useState<'sk' | 'en' | 'de'>('sk');
  const form = draft ?? data.data ?? {};
  const bodyKey = lang === 'sk' ? 'body_sk' : lang === 'en' ? 'body_en' : 'body_de';
  const sieveErrorMessage = (error: unknown) => {
    if (error instanceof ApiError && typeof error.detail.message === 'string') {
      return error.detail.message;
    }
    if (error instanceof ApiError && error.detail.code === 'read_only') {
      return t('settings.filters.readOnly');
    }
    if (error instanceof ApiError && error.detail.code === 'mailbox_send_forbidden') {
      return t('settings.filters.noSend');
    }
    return t('settings.sieveError');
  };
  const save = useMutation({
    mutationFn: () => saveVacation('default', form),
    onSuccess: () => {
      toasts.success(t('settings.saved'));
      void qc.invalidateQueries({ queryKey: ['settings', 'vacation'] });
      void qc.invalidateQueries({ queryKey: ['settings', 'filters'] });
    },
    onError: (error) => toasts.error(sieveErrorMessage(error)),
  });
  const restore = useMutation({
    mutationFn: () => restoreSieve('default'),
    onSuccess: () => {
      toasts.success(t('settings.sieveRestored'));
      void qc.invalidateQueries({ queryKey: ['settings', 'vacation'] });
      void qc.invalidateQueries({ queryKey: ['settings', 'filters'] });
      setDraft(null);
    },
    onError: (error) => toasts.error(sieveErrorMessage(error)),
  });
  const last = form.last_changed as
    { person_name?: string | null; at?: string | null; enabled?: boolean } | null | undefined;
  return (
    <div className="flex max-w-xl flex-col gap-4">
      <Banner kind="info" message={t('settings.vacation.mailboxScope')} />
      <p className="type-small text-text-secondary">{t('settings.vacation.branchHelp')}</p>
      {last?.at ? (
        <p className="type-small text-text-secondary">
          {t('settings.vacation.lastChanged', {
            who: last.person_name || t('settings.vacation.unknownPerson'),
            when: new Date(last.at).toLocaleString('sk-SK'),
            state: last.enabled ? t('settings.vacation.stateOn') : t('settings.vacation.stateOff'),
          })}
        </p>
      ) : null}
      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={Boolean(form.enabled)}
          onChange={(event) => setDraft({ ...form, enabled: event.target.checked })}
        />
        <span className="type-body">{t('settings.vacation.enabled')}</span>
      </label>
      <div className="grid grid-cols-2 gap-3">
        <label className="flex flex-col gap-1">
          <span className="type-label text-text-secondary">{t('settings.vacation.start')}</span>
          <input
            type="datetime-local"
            className="type-body h-9 rounded-sm border border-border-default px-3"
            value={String(form.start ?? '').slice(0, 16)}
            onChange={(event) => setDraft({ ...form, start: event.target.value || null })}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="type-label text-text-secondary">{t('settings.vacation.end')}</span>
          <input
            type="datetime-local"
            className="type-body h-9 rounded-sm border border-border-default px-3"
            value={String(form.end ?? '').slice(0, 16)}
            onChange={(event) => setDraft({ ...form, end: event.target.value || null })}
          />
        </label>
      </div>
      <p className="type-caption text-text-tertiary">{t('settings.vacation.rangeHelp')}</p>
      <label className="flex flex-col gap-1">
        <span className="type-label text-text-secondary">{t('settings.vacation.subject')}</span>
        <input
          className="type-body h-9 rounded-sm border border-border-default px-3"
          value={String(form.subject ?? '')}
          maxLength={120}
          onChange={(event) => setDraft({ ...form, subject: event.target.value })}
        />
      </label>
      <div className="flex gap-2">
        {(['sk', 'en', 'de'] as const).map((code) => (
          <Button
            key={code}
            type="button"
            variant={lang === code ? 'primary' : 'secondary'}
            size="md"
            onClick={() => setLang(code)}
          >
            {code.toUpperCase()}
          </Button>
        ))}
      </div>
      <label className="flex flex-col gap-1">
        <span className="type-label text-text-secondary">{t('settings.vacation.body')}</span>
        <textarea
          className="type-body min-h-[120px] rounded-sm border border-border-default px-3 py-2"
          value={String(form[bodyKey] ?? '')}
          onChange={(event) => setDraft({ ...form, [bodyKey]: event.target.value })}
        />
      </label>
      {(lang === 'en' || lang === 'de') && (
        <p className="type-caption text-text-tertiary">{t('settings.vacation.langHelp')}</p>
      )}
      <label className="flex flex-col gap-1">
        <span className="type-label text-text-secondary">{t('settings.vacation.days')}</span>
        <select
          className="type-body h-9 rounded-sm border border-border-default px-3"
          value={String(form.days ?? 7)}
          onChange={(event) => setDraft({ ...form, days: Number(event.target.value) })}
        >
          {[1, 3, 7].map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
      </label>
      <div className="flex flex-wrap gap-2">
        <Button type="button" onClick={() => save.mutate()} disabled={save.isPending}>
          {t('settings.save')}
        </Button>
        {data.data?.has_backup ? (
          <Button type="button" variant="secondary" onClick={() => restore.mutate()} disabled={restore.isPending}>
            {t('settings.sieveRestore')}
          </Button>
        ) : null}
      </div>
    </div>
  );
}

function ProviderPanel() {
  const { t } = useTranslation();
  const data = useQuery({ queryKey: ['settings', 'provider'], queryFn: () => fetchProvider() });
  if (!data.data) return null;
  const d = data.data;
  return (
    <div className="flex max-w-xl flex-col gap-3">
      <p className="type-body">
        <span className="type-label text-text-secondary">{t('settings.provider.mailbox')}: </span>
        {String(d.email)}
      </p>
      <p className="type-body">
        <span className="type-label text-text-secondary">{t('settings.provider.server')}: </span>
        {String(d.imap_host)}:{String(d.imap_port)}
      </p>
      {d.provider_admin_url ? (
        <a
          className="type-body text-brand-primary-600 underline"
          href={String(d.provider_admin_url)}
          target="_blank"
          rel="noreferrer"
        >
          {t('settings.provider.open')}
        </a>
      ) : (
        <Banner kind="warning" message={t('settings.provider.noUrl')} />
      )}
      <p className="type-small text-text-secondary">{t('settings.provider.vacationHint')}</p>
      <Link className="type-body text-brand-primary-600" to="/settings/vacation">
        {t('settings.provider.toVacation')}
      </Link>
    </div>
  );
}

function SecurityPanel() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const sessions = useQuery({ queryKey: ['settings', 'sessions'], queryFn: fetchSessions });
  return (
    <div className="flex max-w-2xl flex-col gap-3">
      <p className="type-small text-text-secondary">{t('settings.security.loginInfo')}</p>
      <ul className="flex flex-col gap-2">
        {(sessions.data ?? []).map((s) => (
          <li
            key={String(s.id)}
            className="flex items-center justify-between rounded-sm border border-border-default px-3 py-2"
          >
            <span className="type-small">
              {String(s.device_id ?? '—')} · {String(s.last_seen_at ?? '')}
              {s.current ? ` · ${t('settings.security.current')}` : ''}
            </span>
            {!s.current ? (
              <Button
                type="button"
                variant="secondary"
                onClick={() =>
                  void revokeSession(String(s.id)).then(
                    () => void qc.invalidateQueries({ queryKey: ['settings', 'sessions'] }),
                  )
                }
              >
                {t('settings.security.revoke')}
              </Button>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function UsersPanel() {
  const users = useQuery({ queryKey: ['settings', 'users'], queryFn: fetchAdminUsers });
  return (
    <ul className="flex max-w-2xl flex-col gap-2">
      {(users.data ?? []).map((u) => (
        <li key={String(u.id)} className="rounded-sm border border-border-default px-3 py-2 type-body">
          {String(u.email)} · {String(u.kind)} · {u.active ? 'aktívny' : 'neaktívny'}
        </li>
      ))}
    </ul>
  );
}

function BranchesPanel({ sub }: { sub?: string }) {
  const { t } = useTranslation();
  const toasts = useToasts();
  const qc = useQueryClient();
  const branches = useQuery({ queryKey: ['settings', 'branches'], queryFn: fetchAdminBranches });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const current = (branches.data ?? []).find((b) => String(b.id) === selectedId) ?? branches.data?.[0] ?? null;
  const [sigById, setSigById] = useState<Record<string, string>>({});
  const branchId = current ? String(current.id) : '';
  const sig =
    sigById[branchId] ??
    (current ? ((current.signature_template_html as Record<string, string> | undefined)?.sk ?? '') : '');

  const saveSig = useMutation({
    mutationFn: async () => {
      if (!current) return;
      await saveBranch(String(current.id), {
        name: current.name,
        address: current.address,
        phone: current.phone,
        hours: current.hours,
        mailbox_id: current.mailbox_id,
        signature_template_html: { sk: sig },
      });
    },
    onSuccess: () => {
      toasts.success(t('settings.saved'));
      void qc.invalidateQueries({ queryKey: ['settings', 'branches'] });
    },
  });

  if (!current) return <p className="type-body text-text-secondary">{t('settings.branches.empty')}</p>;

  if (sub === 'people' || sub === 'osoby') {
    return (
      <div className="flex flex-col gap-3">
        <ul>
          {((current.people as Record<string, unknown>[]) ?? []).map((p) => (
            <li key={String(p.id)} className="type-body border-b border-border-default py-2">
              {String(p.first_name)} {String(p.last_name)} · {String(p.role)}
              {!p.active ? ' (neaktívna)' : ''}
            </li>
          ))}
        </ul>
        <Button
          type="button"
          variant="secondary"
          onClick={() =>
            void addPersonAdmin(String(current.id), {
              first_name: 'Nová',
              last_name: 'Osoba',
              role: 'sales',
            }).then(() => void qc.invalidateQueries({ queryKey: ['settings', 'branches'] }))
          }
        >
          {t('settings.branches.addPerson')}
        </Button>
      </div>
    );
  }

  if (sub === 'signature' || sub === 'podpis') {
    return (
      <div className="flex max-w-2xl flex-col gap-3">
        <HtmlSignatureEditor
          value={sig}
          onChange={(html) => setSigById((prev) => ({ ...prev, [branchId]: html }))}
          label={t('settings.branches.signature')}
        />
        <Button type="button" onClick={() => saveSig.mutate()} disabled={saveSig.isPending}>
          {t('settings.save')}
        </Button>
      </div>
    );
  }

  if (sub === 'money') {
    // Pilot deploy keeps FEATURE_MONEY=false — no Money bindings in the UI (ADR-010).
    return <Banner kind="info" message={t('settings.branches.moneyHidden')} />;
  }

  return (
    <div className="flex gap-6">
      <ul className="w-48 shrink-0">
        {(branches.data ?? []).map((b) => (
          <li key={String(b.id)}>
            <button
              type="button"
              className={`type-body w-full rounded-sm px-2 py-1.5 text-left ${
                String(b.id) === String(current.id) ? 'bg-brand-primary-50' : 'hover:bg-bg-subtle'
              }`}
              onClick={() => setSelectedId(String(b.id))}
            >
              {String(b.name)}
            </button>
          </li>
        ))}
      </ul>
      <div className="flex flex-col gap-2 type-body">
        <p>
          <strong>{String(current.name)}</strong>
        </p>
        <p className="type-small text-text-secondary">{String(current.mailbox_email ?? '—')}</p>
        <p className="type-small">{String(current.address ?? '')}</p>
        <p className="type-small">{String(current.phone ?? '')}</p>
        <p className="type-small">{String(current.hours ?? '')}</p>
      </div>
    </div>
  );
}

function MailboxesPanel() {
  const { t } = useTranslation();
  const toasts = useToasts();
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ['settings', 'mailboxes'], queryFn: fetchAdminMailboxes });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Record<string, unknown> | null>(null);
  const selected =
    draft && String(draft.id) === selectedId
      ? draft
      : ((list.data ?? []).find((m) => String(m.id) === selectedId) ?? list.data?.[0] ?? null);

  const save = useMutation({
    mutationFn: async () => {
      if (!selected) return;
      await saveMailboxAdmin(String(selected.id), selected);
    },
    onSuccess: () => {
      toasts.success(t('settings.saved'));
      void qc.invalidateQueries({ queryKey: ['settings', 'mailboxes'] });
    },
  });
  return (
    <div className="flex gap-6">
      <ul className="w-56 shrink-0">
        {(list.data ?? []).map((m) => (
          <li key={String(m.id)}>
            <button
              type="button"
              className={`type-body w-full rounded-sm px-2 py-1.5 text-left ${
                selected && String(m.id) === String(selected.id) ? 'bg-brand-primary-50' : 'hover:bg-bg-subtle'
              }`}
              onClick={() => {
                setSelectedId(String(m.id));
                setDraft(m);
              }}
            >
              {String(m.email)}
            </button>
          </li>
        ))}
      </ul>
      {selected ? (
        <div className="flex max-w-xl flex-1 flex-col gap-3">
          <p className="type-body-strong">{String(selected.email)}</p>
          {(['imap_host', 'smtp_host', 'sieve_host', 'provider_admin_url'] as const).map((key) => (
            <label key={key} className="flex flex-col gap-1">
              <span className="type-label text-text-secondary">{key}</span>
              <input
                className="type-body h-9 rounded-sm border border-border-default px-3"
                value={String(selected[key] ?? '')}
                onChange={(event) => {
                  setSelectedId(String(selected.id));
                  setDraft({ ...selected, [key]: event.target.value || null });
                }}
              />
            </label>
          ))}
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={Boolean(selected.sieve_enabled)}
              onChange={(event) => {
                setSelectedId(String(selected.id));
                setDraft({ ...selected, sieve_enabled: event.target.checked });
              }}
            />
            <span className="type-body">{t('settings.mailboxes.sieve')}</span>
          </label>
          <Button type="button" onClick={() => save.mutate()} disabled={save.isPending}>
            {t('settings.save')}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
