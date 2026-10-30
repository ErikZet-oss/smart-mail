import { PREFS_KEY } from '../prefs/prefsApi';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Check, Trash2 } from 'lucide-react';
import { useCallback, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { Banner } from '../../components/Banner';
import { Button } from '../../components/Button';
import { ConfirmDialog } from '../../components/Dialog';
import { ApiError } from '../../lib/api';
import { AppShell } from '../../components/shell/AppShell';
import { useToasts } from '../../components/toastContext';
import { MOBILE_QUERY, useMediaQuery } from '../../lib/useMediaQuery';
import { fetchMe } from '../auth/authApi';
import { BranchDetails, BranchList, BranchLoginSettings, BranchPeople, PersonalAccountPeople } from './BranchAdmin';
import { adminErrorText } from './adminUi';
import { BranchIdentityForm } from './BranchIdentityForm';
import { SettingsFieldControl } from './Field';
import { TwoFactorRow } from './TwoFactor';
import { UsersPanel } from './UsersPanel';
import { HtmlSignatureEditor, SanitizedHtml } from './HtmlSignatureEditor';
import { fillSignature, type SignatureLang } from './signatureHtml';
import { MobileSettingsIndex } from './MobileSettingsIndex';
import { SettingsBreadcrumb, SettingsNav, SettingsSubList, SettingsSubTabs } from './SettingsNav';
import { buildNavItems, isItemActive, TABBED_SECTIONS } from './settingsNavModel';
import { AiKnowledgePanel } from './AiKnowledgePanel';
import { SECTION_TITLES, type SettingsField } from './schema';
import {
  createResponse,
  deleteBranch,
  deleteResponse,
  fetchAdminBranches,
  fetchAdminMailboxes,
  fetchFilters,
  fetchIdentities,
  fetchPreferences,
  fetchProfile,
  fetchProvider,
  fetchResponses,
  fetchSessions,
  fetchSettingsNav,
  fetchSignatureContext,
  fetchSignaturePresets,
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
  signRemotePreviews,
  type NavSection,
  uploadBranchImage,
  uploadIdentityImage,
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

// 01e — the list of keys is W15 (`?`), linked below the switch.
const PREF_FIELDS_SHORTCUTS: SettingsField[] = [
  { id: 'shortcuts_enabled', label: 'Klávesové skratky zapnuté', control: 'switch', default: true },
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
    id: 'show_ai_summary',
    label: 'Zobraziť AI zhrnutie v zozname',
    control: 'switch',
    default: true,
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

const AI_FIELDS: SettingsField[] = [
  {
    id: 'show_ai_summary',
    label: 'Zhrnutia v zozname',
    control: 'switch',
    default: true,
    help: 'Pod predmetom v zozname zobrazí krátke AI zhrnutie. V Klasickom zobrazení je vypnuté.',
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
            <SectionBody
              section={activeSection}
              sub={sub}
              meRole={me.data?.person?.role}
              navSection={nav.data?.sections.find((s) => s.path === activeSection)}
            />
          </div>
        </div>
      </AppShell>
    );
  }

  const sections = nav.data?.sections ?? [];
  const current = sections.find((s) => s.path === activeSection);
  const navItems = buildNavItems(sections);
  const activeItem = navItems.find((i) => isItemActive(i, activeSection, sub));
  const subItem = current?.subs.find((s) => s.path === sub) ?? (sub ? undefined : current?.subs[0]);
  const showSubList =
    Boolean(current && current.subs.length > 1 && current.path !== 'identity') && !TABBED_SECTIONS.has(activeSection);
  const showTabs = Boolean(current && current.subs.length > 1 && TABBED_SECTIONS.has(activeSection));
  const crumbs = [
    activeItem?.admin ? t('settings.adminCrumb') : t('settings.title'),
    activeItem?.title ?? title,
    ...(subItem && current?.path !== 'identity' ? [subItem.title] : []),
  ];
  if (activeSection === 'users' && me.data?.person?.role === 'admin') {
    return (
      <AppShell section="settings">
        <div className="flex h-full min-w-0 flex-1">
          <SettingsNav sections={sections} activeSection={activeSection} sub={sub} />
          <UsersPanel crumbs={crumbs.slice(0, 2)} mobile={false} />
        </div>
      </AppShell>
    );
  }
  if (activeSection === 'branches' && me.data?.person?.role === 'admin') {
    return (
      <AppShell section="settings">
        <div className="flex h-full min-w-0 flex-1">
          <SettingsNav sections={sections} activeSection={activeSection} sub={sub} />
          <BranchesWorkspace section={current} sub={sub} crumbs={crumbs.slice(0, 2)} />
        </div>
      </AppShell>
    );
  }
  const pageTitle =
    activeSection === 'identity' || showTabs
      ? (activeItem?.title ?? title)
      : (subItem?.title ?? activeItem?.title ?? title);

  return (
    <AppShell section="settings">
      <div className="flex h-full min-w-0 flex-1">
        <SettingsNav sections={sections} activeSection={activeSection} sub={sub} />
        {showSubList && current ? <SettingsSubList section={current} sub={sub} /> : null}
        <main className="flex min-w-0 flex-1 flex-col bg-bg-canvas">
          <header className="flex h-[var(--layout-topbar)] shrink-0 items-center border-b border-border-default bg-bg-subtle px-6">
            <SettingsBreadcrumb parts={crumbs} />
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto px-8 py-6">
            <h1 className="type-title mb-6 text-text-primary">{pageTitle}</h1>
            {showTabs && current ? (
              <div className="mb-6">
                <SettingsSubTabs section={current} sub={sub} />
              </div>
            ) : null}
            <SectionBody section={activeSection || 'preferences'} sub={sub} meRole={me.data?.person?.role} />
          </div>
        </main>
      </div>
    </AppShell>
  );
}

function SectionBody({
  section,
  sub,
  meRole,
  navSection,
}: {
  section: string;
  sub?: string;
  meRole?: string;
  navSection?: NavSection;
}) {
  if (section === 'preferences') return <PreferencesPanel sub={sub} />;
  if (section === 'identity' && sub === 'profile') return <ProfilePanel />;
  if (section === 'identity') return <IdentitiesPanel canEditBranch={meRole === 'admin'} />;
  if (section === 'responses') return <ResponsesPanel />;
  if (section === 'filters') return <FiltersPanel />;
  if (section === 'vacation') return <VacationPanel />;
  if (section === 'ai') return <AiPanel />;
  if (section === 'provider') return <ProviderPanel />;
  if (section === 'security') return <SecurityPanel />;
  if (section === 'folders') return <FoldersHint />;
  if (section === 'users') return meRole === 'admin' ? <UsersPanel /> : <AdminOnly />;
  if (section === 'branches') {
    return meRole === 'admin' ? <BranchesWorkspace section={navSection} sub={sub} crumbs={[]} mobile /> : <AdminOnly />;
  }
  if (section === 'mailboxes') return meRole === 'admin' ? <MailboxesPanel /> : <AdminOnly />;
  if (section === 'ai-admin') return meRole === 'admin' ? <AiKnowledgePanel /> : <AdminOnly />;
  return <p className="type-body text-text-secondary">…</p>;
}

/** W12-07 — Phase 2b: list summaries only (autonomy matrix = later milestones). */
function AiPanel() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const toasts = useToasts();
  const prefs = useQuery({ queryKey: ['settings', 'prefs'], queryFn: fetchPreferences });
  const classic = Boolean(prefs.data?.ui?.classic);
  const value = Boolean(prefs.data?.list?.show_ai_summary ?? true);
  const save = useMutation({
    mutationFn: (next: boolean) =>
      savePreferences({
        ui: prefs.data?.ui ?? {},
        list: {
          ...(prefs.data?.list ?? {}),
          show_ai_summary: next,
          page_size: Number(prefs.data?.list?.page_size ?? 50),
        },
        composing: prefs.data?.composing ?? {},
        reading: prefs.data?.reading ?? {},
        shortcuts: prefs.data?.shortcuts ?? {},
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(['settings', 'prefs'], data);
      queryClient.setQueryData(['mail', 'prefs'], data);
      toasts.success(t('settings.saved'));
    },
  });
  return (
    <div className="flex max-w-[var(--layout-settings-form-max)] flex-col gap-3.5" data-testid="settings-ai">
      <h2 className="type-heading text-text-primary">{t('settingsAi.title')}</h2>
      {AI_FIELDS.map((field) => (
        <SettingsFieldControl
          key={field.id}
          field={field}
          value={value}
          disabled={classic || save.isPending}
          onChange={(next) => save.mutate(Boolean(next))}
        />
      ))}
      {classic ? <Banner kind="info" message={t('classic.banner')} /> : null}
      <p className="type-small text-text-secondary">{t('settingsAi.comingAutonomy')}</p>
    </div>
  );
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
  const queryClient = useQueryClient();
  const prefs = useQuery({ queryKey: ['settings', 'prefs'], queryFn: fetchPreferences });
  const [draft, setDraft] = useState<{
    ui?: Record<string, unknown>;
    list?: Record<string, unknown>;
    composing?: Record<string, unknown>;
    shortcuts?: Record<string, unknown>;
  } | null>(null);
  const ui = draft?.ui ?? prefs.data?.ui ?? {};
  const list = draft?.list ?? {
    ...(prefs.data?.list ?? {}),
    page_size: String(prefs.data?.list?.page_size ?? 50),
  };
  const composing = draft?.composing ?? prefs.data?.composing ?? {};
  const shortcuts = draft?.shortcuts ?? {
    shortcuts_enabled: prefs.data?.shortcuts?.shortcuts_enabled ?? true,
  };

  const save = useMutation({
    mutationFn: () =>
      savePreferences({
        ui,
        list: { ...list, page_size: Number(list.page_size ?? 50) },
        composing,
        reading: prefs.data?.reading ?? {},
        shortcuts,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: PREFS_KEY });
      toasts.success(t('settings.saved'));
    },
  });

  const which = sub ?? 'ui';
  const mobile = useMediaQuery(MOBILE_QUERY);
  // M9: Vzhľad page also exposes Oneskorenie odoslania (SETTINGS_SPEC §M9 / 01d).
  const showMobileUndo = mobile && which === 'ui';
  const isList = which === 'mailbox-view' || which === 'list';
  const fields = isList
    ? PREF_FIELDS_LIST
    : which === 'composing'
      ? PREF_FIELDS_COMPOSING
      : which === 'shortcuts'
        ? PREF_FIELDS_SHORTCUTS
        : PREF_FIELDS_UI;
  const state = isList ? list : which === 'composing' ? composing : which === 'shortcuts' ? shortcuts : ui;
  const patch = (value: Record<string, unknown>) => {
    if (isList) setDraft({ ui, list: value, composing, shortcuts });
    else if (which === 'composing') setDraft({ ui, list, composing: value, shortcuts });
    else if (which === 'shortcuts') setDraft({ ui, list, composing, shortcuts: value });
    else setDraft({ ui: value, list, composing, shortcuts });
  };
  const undoField = PREF_FIELDS_COMPOSING.find((f) => f.id === 'undo_send_seconds');

  return (
    <div className="flex max-w-[var(--layout-settings-form-max)] flex-col gap-3.5">
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
          onChange={(value) => setDraft({ ui, list, composing: { ...composing, [undoField.id]: value }, shortcuts })}
        />
      ) : null}
      <Button
        type="button"
        className="mt-4 self-start"
        icon={<Check size={16} aria-hidden />}
        onClick={() => save.mutate()}
        disabled={save.isPending}
      >
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
      <SanitizedHtml
        className="rounded-sm border border-border-default p-3"
        html={String(form.signature_preview_html ?? '')}
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

function signatureErrorText(t: (key: string) => string, error: unknown): string {
  if (!(error instanceof ApiError)) return t('settings.signature.saveFailed');
  const code = error.detail.code;
  if (code === 'signature_sk_required') return t('settings.signature.skRequired');
  if (code === 'unknown_signature_variable') return t('settings.signature.unknownVariable');
  if (code === 'signature_too_large') return t('settings.signature.tooLarge');
  if (code === 'image_too_large') return t('settings.signature.imageTooLarge');
  if (code === 'image_limit') return t('settings.signature.imageLimit');
  if (code === 'image_type') return t('settings.signature.imageType');
  return t('settings.signature.saveFailed');
}

function IdentitiesPanel({ canEditBranch }: { canEditBranch: boolean }) {
  const { t } = useTranslation();
  const toasts = useToasts();
  const list = useQuery({ queryKey: ['settings', 'identities'], queryFn: () => fetchIdentities() });
  const context = useQuery({ queryKey: ['settings', 'signature-context'], queryFn: () => fetchSignatureContext() });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Record<string, unknown> | null>(null);
  const [lang, setLang] = useState<SignatureLang>('sk');
  const [stripped, setStripped] = useState<Record<string, string[]>>({});
  const [remotes, setRemotes] = useState<Record<string, string>>({});
  const asked = useRef(new Set<string>());
  const server = (list.data ?? []).find((i) => String(i.id) === selectedId) ?? list.data?.[0];
  const form = draft && String(draft.id) === String(server?.id) ? draft : (server ?? null);
  const htmls = (form?.signature_html as Record<string, string> | undefined) ?? {};
  const images = (form?.signature_images as { cid: string; preview_url: string }[] | undefined) ?? [];
  const previews: Record<string, string> = { ...remotes };
  for (const image of images) previews[image.cid] = image.preview_url;
  const onRemoteUrls = useCallback((urls: string[]) => {
    const fresh = urls.filter((url) => !asked.current.has(url));
    if (!fresh.length) return;
    for (const url of fresh) asked.current.add(url);
    void signRemotePreviews(fresh)
      .then((data) => setRemotes((prev) => ({ ...prev, ...data.previews })))
      .catch(() => undefined);
  }, []);
  const save = useMutation({
    mutationFn: async () => {
      if (!form?.id) return null;
      return saveIdentity(String(form.id), form);
    },
    onSuccess: (saved) => {
      if (!saved) return;
      setDraft(saved);
      setStripped((saved.signature_stripped as Record<string, string[]>) ?? {});
      toasts.success(t('settings.saved'));
    },
    onError: (error) => toasts.error(signatureErrorText(t, error)),
  });
  if (context.data?.branch_managed) {
    return (
      <div className="flex max-w-3xl flex-col gap-6">
        <BranchIdentityForm canEdit={canEditBranch} />
        <section className="flex flex-col gap-3">
          <h2 className="type-heading text-text-primary">{t('settings.identity.signature')}</h2>
          <div className="type-small flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-border-default bg-bg-subtle px-4 py-3 text-text-primary">
            <span className="flex-1">{t('settings.identity.branchPreview')}</span>
            <Link to="/settings/branches/signature" className="type-label text-brand-primary-600">
              {t('settings.identity.editTemplate')}
            </Link>
          </div>
          <SanitizedHtml className="rounded-md border border-border-default p-4" html={context.data.preview_html} />
        </section>
      </div>
    );
  }
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
                setStripped({});
              }}
            >
              {String(i.display_name)} &lt;{String(i.email)}&gt;
            </button>
          </li>
        ))}
      </ul>
      {form?.id ? (
        <div className="flex min-w-0 max-w-3xl flex-1 flex-col gap-3">
          <label className="flex flex-col gap-1">
            <span className="type-label text-text-secondary">{t('settings.identity.displayName')}</span>
            <input
              className="type-body h-9 rounded-sm border border-border-default px-3"
              value={String(form.display_name ?? '')}
              onChange={(event) => setDraft({ ...form, display_name: event.target.value })}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="type-label text-text-secondary">{t('settings.identity.email')}</span>
            <input
              className="type-body h-9 rounded-sm border border-border-default px-3"
              value={String(form.email ?? '')}
              onChange={(event) => setDraft({ ...form, email: event.target.value })}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="type-label text-text-secondary">{t('settings.identity.organization')}</span>
            <input
              className="type-body h-9 rounded-sm border border-border-default px-3"
              value={String(form.organization ?? '')}
              onChange={(event) => setDraft({ ...form, organization: event.target.value })}
            />
          </label>
          <label className="type-body flex items-center gap-2">
            <input
              type="checkbox"
              checked={Boolean(form.is_default)}
              onChange={(event) => setDraft({ ...form, is_default: event.target.checked })}
            />
            {t('settings.identity.defaultIdentity')}
          </label>
          <HtmlSignatureEditor
            label={t('settings.identity.signature')}
            languages
            language={lang}
            onLanguage={setLang}
            value={htmls[lang] ?? ''}
            imagePreviews={previews}
            onRemoteUrls={onRemoteUrls}
            stripped={stripped[lang]}
            uploadImage={async (file) => {
              const saved = await uploadIdentityImage(String(form.id), file);
              setDraft({ ...form, signature_images: [...images, saved] });
              return saved;
            }}
            onChange={(html) => setDraft({ ...form, signature_html: { ...htmls, [lang]: html } })}
          />
          <div className="flex gap-2">
            <Button type="button" onClick={() => save.mutate()} disabled={save.isPending}>
              {t('settings.save')}
            </Button>
            <Button
              type="button"
              variant="secondary"
              onClick={() => {
                setDraft(server ?? null);
                setStripped({});
              }}
            >
              {t('common.cancel')}
            </Button>
          </div>
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
      <HtmlSignatureEditor
        value={body}
        onChange={setBody}
        label={t('settings.responses.body')}
        footer="plain"
        maxBytes={20_000}
      />
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
  const sieveUnavailable = Boolean(data.data?.sieve_unavailable);
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
      {sieveUnavailable ? (
        <Banner
          kind="warning"
          message={
            (typeof data.data?.sieve_message === 'string' && data.data.sieve_message) || t('settings.sieveUnavailable')
          }
        />
      ) : (
        <Banner kind="info" message={t('settings.filters.mailboxScope')} />
      )}
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
              aria-label={t('settings.filters.ruleName')}
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
  const sieveUnavailable = Boolean(form.sieve_unavailable);
  return (
    <div className="flex max-w-xl flex-col gap-4">
      {sieveUnavailable ? (
        <Banner
          kind="warning"
          message={(typeof form.sieve_message === 'string' && form.sieve_message) || t('settings.sieveUnavailable')}
        />
      ) : (
        <Banner kind="info" message={t('settings.vacation.mailboxScope')} />
      )}
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
      <TwoFactorRow />
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

type BranchPerson = {
  id: string;
  first_name?: string;
  last_name?: string;
  function?: string;
  phone?: string;
  mobile?: string;
  personal_email?: string;
};

function branchPreviewValues(
  person: BranchPerson | undefined,
  branch: Record<string, unknown>,
): Record<string, string> {
  const initials = `${(person?.first_name ?? '').slice(0, 1)}${(person?.last_name ?? '').slice(0, 1)}`.toUpperCase();
  const photo = initials
    ? `<div style="width:72px;height:80px;background:var(--brand-primary-600);color:var(--text-on-primary);text-align:center;line-height:80px;font-weight:700;clip-path:polygon(50% 0,100% 25%,100% 75%,50% 100%,0 75%,0 25%)">${initials}</div>`
    : '';
  return {
    meno: person?.first_name ?? '',
    priezvisko: person?.last_name ?? '',
    funkcia: person?.function ?? '',
    telefon: person?.phone ?? '',
    mobil: person?.mobile ?? '',
    email_osobny: person?.personal_email ?? '',
    email_pobocky: String(branch.mailbox_email ?? ''),
    pobocka: String(branch.name ?? ''),
    adresa_pobocky: String(branch.address ?? ''),
    telefon_pobocky: String(branch.phone ?? ''),
    oteviracie_hodiny: String(branch.hours ?? ''),
    web: 'www.smartsro.sk',
    firma: 'Smart s.r.o.',
    fotka: photo,
    logo: '<img src="/logo-smart.svg" alt="SMART" width="96" height="33">',
  };
}

/** W12-11 Pobočky a osoby (Figma `68:60641`, `68:61587`, `72:62234`): the branch list as its own full-height
 * column, the branch name as the page title, „Vymazať pobočku“ in the header and the tabs Údaje · Osoby (count) ·
 * Podpis · Prihlasovanie · Money. On a phone the list sits above the tabs. */
function BranchesWorkspace({
  section,
  sub,
  crumbs,
  mobile = false,
}: {
  section?: NavSection;
  sub?: string;
  crumbs: string[];
  mobile?: boolean;
}) {
  const { t } = useTranslation();
  const branches = useQuery({ queryKey: ['settings', 'branches'], queryFn: fetchAdminBranches });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const all = branches.data ?? [];
  const current = all.find((b) => String(b.id) === selectedId) ?? all[0] ?? null;
  const subItem = section?.subs.find((s) => s.path === sub) ?? section?.subs[0];
  const activePeople = current
    ? ((current.people as { active: boolean }[] | undefined) ?? []).filter((p) => p.active).length
    : 0;
  const list = (
    <BranchList
      branches={all}
      currentId={current ? String(current.id) : ''}
      onSelect={setSelectedId}
      column={!mobile}
    />
  );
  const body = current ? (
    <>
      <h1 className="type-title mb-6 text-text-primary">{String(current.name)}</h1>
      {section ? (
        <div className="mb-6">
          <SettingsSubTabs section={section} sub={sub} counts={{ people: activePeople }} />
        </div>
      ) : null}
      <BranchesPanel key={String(current.id)} sub={sub} current={current} branches={all} />
    </>
  ) : (
    <p className="type-body text-text-secondary">{t('settings.branches.empty')}</p>
  );
  const remove = current ? (
    <button
      type="button"
      onClick={() => setDeleting(true)}
      className="type-label inline-flex shrink-0 items-center gap-1.5 rounded-xs text-brand-primary-700 hover:underline"
    >
      <Trash2 size={16} aria-hidden="true" />
      {t('settings.branches.delete')}
    </button>
  ) : null;
  const dialog =
    deleting && current ? (
      <DeleteBranchDialog
        branch={current}
        onClose={() => setDeleting(false)}
        onDeleted={() => {
          setDeleting(false);
          setSelectedId(null);
        }}
      />
    ) : null;

  if (mobile) {
    return (
      <div className="flex min-w-0 flex-col gap-4" data-testid="branches-workspace">
        {list}
        {current ? <div className="flex justify-end">{remove}</div> : null}
        {body}
        {dialog}
      </div>
    );
  }
  return (
    <>
      {list}
      <main className="flex min-w-0 flex-1 flex-col bg-bg-canvas" data-testid="branches-workspace">
        <header className="flex h-[var(--layout-topbar)] shrink-0 items-center gap-4 border-b border-border-default bg-bg-subtle px-6">
          <div className="min-w-0 flex-1">
            <SettingsBreadcrumb
              parts={[...crumbs, ...(current ? [String(current.name)] : []), ...(subItem ? [subItem.title] : [])]}
            />
          </div>
          {remove}
        </header>
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-8 pt-6">{body}</div>
      </main>
      {dialog}
    </>
  );
}

function DeleteBranchDialog({
  branch,
  onClose,
  onDeleted,
}: {
  branch: Record<string, unknown>;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const { t } = useTranslation();
  const toasts = useToasts();
  const qc = useQueryClient();
  const remove = useMutation({
    mutationFn: () => deleteBranch(String(branch.id)),
    onSuccess: () => {
      toasts.success(t('settings.branches.deleted'));
      void qc.invalidateQueries({ queryKey: ['settings', 'branches'] });
      onDeleted();
    },
    onError: (error) => {
      toasts.error(adminErrorText(t, error));
      onClose();
    },
  });
  return (
    <ConfirmDialog
      title={t('settings.branches.deleteTitle', { name: String(branch.name) })}
      body={t('settings.branches.deleteBody')}
      confirmLabel={t('settings.branches.delete')}
      busy={remove.isPending}
      onConfirm={() => remove.mutate()}
      onClose={onClose}
    />
  );
}

function BranchesPanel({
  sub,
  current,
  branches,
}: {
  sub?: string;
  current: Record<string, unknown>;
  branches: Record<string, unknown>[];
}) {
  const { t } = useTranslation();
  const toasts = useToasts();
  const qc = useQueryClient();
  const presets = useQuery({
    queryKey: ['settings', 'signature-presets'],
    queryFn: fetchSignaturePresets,
    enabled: sub === 'signature' || sub === 'podpis',
  });
  const [lang, setLang] = useState<SignatureLang>('sk');
  const [personId, setPersonId] = useState<string>('');
  const [templatesById, setTemplatesById] = useState<Record<string, Record<string, string>>>({});
  const [stripped, setStripped] = useState<Record<string, string[]>>({});
  const [remotes, setRemotes] = useState<Record<string, string>>({});
  const [restoreOpen, setRestoreOpen] = useState(false);
  const asked = useRef(new Set<string>());
  const branchId = String(current.id);
  const stored = (current?.signature_template_html as Record<string, string> | undefined) ?? {};
  const templates = templatesById[branchId] ?? stored;
  const sig = templates[lang] ?? '';
  const images = (current?.signature_images as { cid: string; preview_url: string }[] | undefined) ?? [];
  const previews: Record<string, string> = { ...remotes };
  for (const image of images) previews[image.cid] = image.preview_url;
  const onRemoteUrls = useCallback((urls: string[]) => {
    const fresh = urls.filter((url) => !asked.current.has(url));
    if (!fresh.length) return;
    for (const url of fresh) asked.current.add(url);
    void signRemotePreviews(fresh)
      .then((data) => setRemotes((prev) => ({ ...prev, ...data.previews })))
      .catch(() => undefined);
  }, []);

  const saveSig = useMutation({
    mutationFn: async () => {
      return saveBranch(String(current.id), {
        name: current.name,
        address: current.address,
        phone: current.phone,
        hours: current.hours,
        mailbox_id: current.mailbox_id,
        signature_template_html: templates,
      });
    },
    onSuccess: (saved) => {
      if (saved?.signature_template_html && branchId) {
        setTemplatesById((prev) => ({
          ...prev,
          [branchId]: saved.signature_template_html as Record<string, string>,
        }));
        setStripped((saved.signature_stripped as Record<string, string[]>) ?? {});
      }
      toasts.success(t('settings.saved'));
      void qc.invalidateQueries({ queryKey: ['settings', 'branches'] });
    },
    onError: (error) => toasts.error(signatureErrorText(t, error)),
  });

  if (sub === 'people' || sub === 'osoby') {
    return (
      <div className="flex min-w-0 flex-col gap-8 pb-6">
        <BranchPeople branch={current} branches={branches} />
        <PersonalAccountPeople branches={branches} />
      </div>
    );
  }

  if (sub === 'signature' || sub === 'podpis') {
    const people = (current.people as BranchPerson[]) ?? [];
    const person = people.find((item) => item.id === personId) ?? people[0];
    const preview = fillSignature(sig, branchPreviewValues(person, current));
    return (
      <div className="flex max-w-3xl flex-col gap-3 pb-6">
        <HtmlSignatureEditor
          label={t('settings.branches.signature')}
          languages
          language={lang}
          onLanguage={setLang}
          variables
          presets={{ karta: presets.data?.karta[lang], text: presets.data?.text[lang] }}
          value={sig}
          imagePreviews={previews}
          onRemoteUrls={onRemoteUrls}
          stripped={stripped[lang]}
          uploadImage={
            branchId
              ? async (file) => {
                  const saved = await uploadBranchImage(branchId, file);
                  void qc.invalidateQueries({ queryKey: ['settings', 'branches'] });
                  return saved;
                }
              : undefined
          }
          onChange={(html) =>
            setTemplatesById((prev) => ({
              ...prev,
              [branchId]: { ...(prev[branchId] ?? stored), [lang]: html },
            }))
          }
        />
        <div className="flex gap-2">
          <Button type="button" onClick={() => saveSig.mutate()} disabled={saveSig.isPending}>
            {t('settings.save')}
          </Button>
          <Button type="button" variant="secondary" onClick={() => setRestoreOpen(true)}>
            {t('settings.signature.restore')}
          </Button>
        </div>
        <div className="flex flex-col gap-2 rounded-md border border-border-default p-3">
          <span className="type-label text-text-secondary">{t('settings.signature.preview')}</span>
          <label className="flex max-w-xs flex-col gap-1">
            <span className="type-caption text-text-tertiary">{t('settings.signature.previewPerson')}</span>
            <select
              className="type-body h-9 rounded-sm border border-border-default px-2"
              value={person?.id ?? ''}
              onChange={(event) => setPersonId(event.target.value)}
            >
              {people.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.first_name} {item.last_name}
                </option>
              ))}
            </select>
          </label>
          <SanitizedHtml className="rounded-sm bg-bg-subtle p-3" html={preview} />
        </div>
        {restoreOpen && presets.data ? (
          <ConfirmDialog
            title={t('settings.signature.restoreTitle')}
            body={t('settings.signature.restoreBody')}
            confirmLabel={t('settings.signature.restore')}
            onClose={() => setRestoreOpen(false)}
            onConfirm={() => {
              setTemplatesById((prev) => ({ ...prev, [branchId]: { ...presets.data.karta } }));
              setRestoreOpen(false);
            }}
          />
        ) : null}
      </div>
    );
  }

  if (sub === 'login' || sub === 'prihlasovanie') {
    return <BranchLoginSettings key={branchId} branch={current} />;
  }

  if (sub === 'money') {
    // Pilot deploy keeps FEATURE_MONEY=false — no Money bindings in the UI (ADR-010).
    return <Banner kind="info" message={t('settings.branches.moneyHidden')} />;
  }

  return <BranchDetails key={branchId} branch={current} />;
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
