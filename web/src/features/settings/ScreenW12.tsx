import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';

import { Button } from '../../components/Button';
import { Banner } from '../../components/Banner';
import { AppShell } from '../../components/shell/AppShell';
import { useToasts } from '../../components/toastContext';
import { fetchMe } from '../auth/authApi';
import { SettingsFieldControl } from './Field';
import { HtmlSignatureEditor } from './HtmlSignatureEditor';
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
  revokeSession,
  saveBranch,
  saveFilters,
  saveIdentity,
  saveMailboxAdmin,
  savePreferences,
  saveProfile,
  saveVacation,
} from './settingsApi';

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

/** W12 Nastavenia — Phase 1f sections 01–06, 09, 09b, 10–12. */
export function ScreenW12() {
  const { t } = useTranslation();
  const { section = 'preferences', sub } = useParams();
  const me = useQuery({ queryKey: ['me'], queryFn: fetchMe, retry: false });
  const nav = useQuery({ queryKey: ['settings', 'nav'], queryFn: fetchSettingsNav });
  const title =
    section === 'identity' && sub === 'profile'
      ? t('settings.profile.title')
      : (SECTION_TITLES[section] ?? t('settings.title'));

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
                  section === s.path
                    ? 'bg-brand-primary-50 text-brand-primary-700'
                    : 'text-text-primary hover:bg-bg-muted'
                }`}
              >
                {s.title}
              </Link>
              {section === s.path && s.subs.length > 0 ? (
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
            <SectionBody section={section} sub={sub} meRole={me.data?.person?.role} />
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
  const data = useQuery({ queryKey: ['settings', 'filters'], queryFn: () => fetchFilters() });
  const [draft, setDraft] = useState<Record<string, unknown>[] | null>(null);
  const rules = draft ?? data.data?.rules ?? [];
  const save = useMutation({
    mutationFn: () => saveFilters('default', rules),
    onSuccess: () => toasts.success(t('settings.saved')),
    onError: () => toasts.error(t('settings.sieveError')),
  });
  return (
    <div className="flex max-w-2xl flex-col gap-4">
      <p className="type-small text-text-secondary">{t('settings.filtersHelp')}</p>
      {rules.map((rule, index) => (
        <div key={String(rule.id ?? index)} className="rounded-sm border border-border-default p-3">
          <input
            className="type-body mb-2 h-9 w-full rounded-sm border border-border-default px-3"
            value={String(rule.name ?? '')}
            onChange={(event) => {
              const next = [...rules];
              next[index] = { ...rule, name: event.target.value };
              setDraft(next);
            }}
          />
          <label className="flex items-center gap-2 type-small">
            <input
              type="checkbox"
              checked={Boolean(rule.enabled)}
              onChange={(event) => {
                const next = [...rules];
                next[index] = { ...rule, enabled: event.target.checked };
                setDraft(next);
              }}
            />
            {t('settings.filters.enabled')}
          </label>
        </div>
      ))}
      <Button
        type="button"
        variant="secondary"
        onClick={() =>
          setDraft([
            ...rules,
            {
              id: `new-${Date.now()}`,
              name: 'Nový filter',
              enabled: true,
              match: 'allof',
              conditions: [{ field: 'from', op: 'contains', value: '' }],
              actions: [{ type: 'fileinto', value: 'INBOX' }],
            },
          ])
        }
      >
        {t('settings.filters.add')}
      </Button>
      <Button type="button" onClick={() => save.mutate()} disabled={save.isPending}>
        {t('settings.save')}
      </Button>
    </div>
  );
}

function VacationPanel() {
  const { t } = useTranslation();
  const toasts = useToasts();
  const data = useQuery({ queryKey: ['settings', 'vacation'], queryFn: () => fetchVacation() });
  const [draft, setDraft] = useState<Record<string, unknown> | null>(null);
  const form = draft ?? data.data ?? {};
  const save = useMutation({
    mutationFn: () => saveVacation('default', form),
    onSuccess: () => toasts.success(t('settings.saved')),
    onError: () => toasts.error(t('settings.sieveError')),
  });
  return (
    <div className="flex max-w-xl flex-col gap-4">
      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={Boolean(form.enabled)}
          onChange={(event) => setDraft({ ...form, enabled: event.target.checked })}
        />
        <span className="type-body">{t('settings.vacation.enabled')}</span>
      </label>
      <label className="flex flex-col gap-1">
        <span className="type-label text-text-secondary">{t('settings.vacation.subject')}</span>
        <input
          className="type-body h-9 rounded-sm border border-border-default px-3"
          value={String(form.subject ?? '')}
          onChange={(event) => setDraft({ ...form, subject: event.target.value })}
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className="type-label text-text-secondary">{t('settings.vacation.body')}</span>
        <textarea
          className="type-body min-h-[120px] rounded-sm border border-border-default px-3 py-2"
          value={String(form.body_sk ?? '')}
          onChange={(event) => setDraft({ ...form, body_sk: event.target.value })}
        />
      </label>
      <Button type="button" onClick={() => save.mutate()} disabled={save.isPending}>
        {t('settings.save')}
      </Button>
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
  const current =
    (branches.data ?? []).find((b) => String(b.id) === selectedId) ?? branches.data?.[0] ?? null;
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
    return <Banner kind="info" message={t('settings.branches.moneyLater')} />;
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
