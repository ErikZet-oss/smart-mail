import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  Clock,
  Download,
  Folder,
  Mail,
  MoreHorizontal,
  Pencil,
  Phone,
  Plus,
  Search,
  SquarePen,
  Trash2,
  Upload,
  User,
  UserPlus,
  Users,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Navigate, useNavigate, useParams } from 'react-router-dom';

import { Avatar } from '../../components/Avatar';
import { Button } from '../../components/Button';
import { Dialog } from '../../components/Dialog';
import { AppShell } from '../../components/shell/AppShell';
import { useToasts } from '../../components/toastContext';
import { ApiError } from '../../lib/api';
import { MOBILE_QUERY, useMediaQuery } from '../../lib/useMediaQuery';
import { fetchMe } from '../auth/authApi';
import {
  booksKey,
  contactsKey,
  createContact,
  deleteContact,
  exportVcardUrl,
  fetchBooks,
  fetchContacts,
  fetchGroups,
  groupsKey,
  importVcard,
  initialsOf,
  updateContact,
  type Contact,
  type ContactIn,
} from './contactsApi';

type EditorMode = 'create' | 'edit' | null;

function emptyForm(): ContactIn {
  return {
    display_name: '',
    first_name: '',
    last_name: '',
    organization: '',
    notes: '',
    emails: [{ email: '', type: 'work' }],
    phones: [],
    group_ids: [],
  };
}

function toForm(c: Contact): ContactIn {
  return {
    display_name: c.display_name,
    first_name: c.first_name ?? '',
    last_name: c.last_name ?? '',
    organization: c.organization ?? '',
    notes: c.notes ?? '',
    emails: c.emails.length ? c.emails.map((e) => ({ ...e })) : [{ email: '', type: 'work' }],
    phones: c.phones.map((p) => ({ ...p })),
    group_ids: [...c.group_ids],
  };
}

/** W9 / M15 Kontakty — Osobné / Zdieľané; mobile list+detail stack (SCREENS_SPEC). */
export function ScreenW9() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const mobile = useMediaQuery(MOBILE_QUERY);
  const { book: bookParam, contactId } = useParams<{ book?: string; contactId?: string }>();
  const toasts = useToasts();
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [filter, setFilter] = useState('');
  const [editor, setEditor] = useState<EditorMode>(null);
  const [form, setForm] = useState<ContactIn>(emptyForm());
  const [importOpen, setImportOpen] = useState(false);
  const [onDuplicate, setOnDuplicate] = useState<'merge' | 'skip'>('skip');
  const [importError, setImportError] = useState<string | null>(null);

  const me = useQuery({ queryKey: ['me'], queryFn: fetchMe, retry: false });
  /** API 403 for viewers on every book; hide Upraviť / Zmazať / Import (shared-book debt). */
  const canWrite = me.data?.person?.role !== 'viewer';
  const books = useQuery({ queryKey: booksKey, queryFn: fetchBooks });
  const activeBook = useMemo(() => {
    if (!books.data?.length) return null;
    if (bookParam === 'shared') return books.data.find((b) => b.kind === 'shared') ?? books.data[0] ?? null;
    if (bookParam === 'personal' || !bookParam)
      return books.data.find((b) => b.kind === 'personal') ?? books.data[0] ?? null;
    return books.data.find((b) => b.id === bookParam) ?? books.data[0] ?? null;
  }, [books.data, bookParam]);

  useEffect(() => {
    if (!books.data?.length || !activeBook) return;
    const slug = activeBook.kind === 'shared' ? 'shared' : 'personal';
    if (bookParam !== slug && bookParam !== activeBook.id) {
      navigate(`/contacts/${slug}${contactId ? `/${contactId}` : ''}`, { replace: true });
    }
  }, [books.data, activeBook, bookParam, contactId, navigate]);

  const contacts = useQuery({
    queryKey: contactsKey(activeBook?.id ?? '', filter),
    queryFn: () => fetchContacts(activeBook?.id ?? '', filter),
    enabled: Boolean(activeBook),
  });
  const groups = useQuery({
    queryKey: groupsKey(activeBook?.id ?? ''),
    queryFn: () => fetchGroups(activeBook?.id ?? ''),
    enabled: Boolean(activeBook),
  });

  const selected = useMemo(() => {
    if (contactId) return contacts.data?.find((c) => c.id === contactId) ?? null;
    if (mobile) return null;
    return contacts.data?.[0] ?? null;
  }, [contacts.data, contactId, mobile]);

  useEffect(() => {
    if (mobile) return; // M15: stay on list until the user opens a contact
    if (!activeBook || !contacts.data?.length) return;
    if (contactId && contacts.data.some((c) => c.id === contactId)) return;
    if (contacts.data[0] && !contactId) {
      navigate(`/contacts/${bookParam ?? activeBook.kind}/${contacts.data[0].id}`, { replace: true });
    }
  }, [contacts.data, contactId, activeBook, bookParam, navigate, mobile]);

  const save = useMutation({
    mutationFn: async () => {
      if (!activeBook) throw new Error('no book');
      const body: ContactIn = {
        ...form,
        display_name: form.display_name.trim(),
        emails: (form.emails ?? []).filter((e) => e.email.trim()),
        phones: (form.phones ?? []).filter((p) => p.number.trim()),
      };
      if (editor === 'edit' && selected) return updateContact(selected.id, body);
      return createContact(activeBook.id, body);
    },
    onSuccess: (c) => {
      void queryClient.invalidateQueries({ queryKey: booksKey });
      void queryClient.invalidateQueries({ queryKey: ['contacts', activeBook?.id] });
      setEditor(null);
      toasts.success(t('contacts.saved'));
      navigate(`/contacts/${bookParam ?? activeBook?.kind}/${c.id}`);
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 403) toasts.error(t('contacts.readOnly'));
      else toasts.error(t('contacts.errors.save'));
    },
  });

  const remove = useMutation({
    mutationFn: () => {
      if (!selected) throw new Error('no contact');
      return deleteContact(selected.id);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['contacts', activeBook?.id] });
      void queryClient.invalidateQueries({ queryKey: booksKey });
      toasts.success(t('contacts.deleted'));
      navigate(`/contacts/${bookParam ?? 'personal'}`);
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 403) toasts.error(t('contacts.readOnly'));
      else toasts.error(t('contacts.errors.delete'));
    },
  });

  const doImport = useMutation({
    mutationFn: (file: File) => {
      if (!activeBook) throw new Error('no book');
      return importVcard(activeBook.id, file, onDuplicate);
    },
    onSuccess: (stats) => {
      void queryClient.invalidateQueries({ queryKey: ['contacts', activeBook?.id] });
      setImportOpen(false);
      setImportError(null);
      toasts.success(t('contacts.importDone', stats));
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 403) setImportError(t('contacts.readOnly'));
      else if (err instanceof ApiError && err.status === 413) setImportError(t('contacts.errors.tooLarge'));
      else if (err instanceof ApiError && err.status === 422) setImportError(t('contacts.errors.badVcard'));
      else setImportError(t('contacts.errors.import'));
    },
  });

  if (books.isError) {
    return (
      <AppShell section="contacts">
        <div className="flex flex-1 items-center justify-center p-8">
          <p className="type-body text-danger-600">{t('contacts.errors.load')}</p>
        </div>
      </AppShell>
    );
  }

  if (!books.data) {
    return (
      <AppShell section="contacts">
        <main className="flex-1 bg-bg-subtle" aria-busy="true" />
      </AppShell>
    );
  }

  if (!activeBook) return <Navigate to="/contacts/personal" replace />;

  const bookSlug = activeBook.kind === 'shared' ? 'shared' : 'personal';
  const empty = (contacts.data?.length ?? 0) === 0 && !filter.trim();
  const mobileDetail = mobile && Boolean(contactId) && selected;

  return (
    <AppShell section="contacts">
      <div
        className="flex min-h-0 min-w-0 flex-1"
        data-testid={mobile ? (mobileDetail ? 'screen-m15-detail' : 'screen-m15') : undefined}
      >
        {/* Left: address books + groups (desktop) */}
        <aside className="hidden w-[var(--layout-folders)] shrink-0 flex-col border-r border-border-default bg-bg-subtle sm:flex">
          <header className="flex h-14 items-center justify-between border-b border-border-default px-4">
            <h1 className="type-body-strong text-text-primary">{t('contacts.title')}</h1>
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto px-2 py-3">
            <p className="type-caption px-2 pb-1.5 text-text-secondary">{t('contacts.books')}</p>
            {books.data.map((b) => {
              const slug = b.kind === 'shared' ? 'shared' : 'personal';
              const active = activeBook.id === b.id;
              return (
                <button
                  key={b.id}
                  type="button"
                  onClick={() => navigate(`/contacts/${slug}`)}
                  className={`type-small flex h-8 w-full items-center gap-2.5 rounded-sm px-2 text-left ${
                    active
                      ? 'bg-brand-primary-50 font-semibold text-brand-primary-700'
                      : 'text-text-primary hover:bg-bg-muted'
                  }`}
                >
                  {b.kind === 'shared' ? (
                    <Users size={16} aria-hidden="true" className="shrink-0" />
                  ) : (
                    <User size={16} aria-hidden="true" className="shrink-0" />
                  )}
                  <span className="truncate">
                    {b.kind === 'shared' ? t('contacts.shared') : t('contacts.personal')}
                  </span>
                </button>
              );
            })}
            {/* Money address book stays hidden until FEATURE_MONEY (Phase 3+). */}
            <div
              className="type-small flex h-8 items-center gap-2.5 px-2 text-text-secondary"
              title={t('common.comingSoon')}
            >
              <Clock size={16} aria-hidden="true" className="shrink-0" />
              {t('contacts.recent')}
            </div>
            {(groups.data?.length ?? 0) > 0 ? (
              <>
                <p className="type-caption mt-4 px-2 pb-1.5 text-text-secondary">{t('contacts.groups')}</p>
                {groups.data?.map((g) => (
                  <div key={g.id} className="type-small flex h-8 items-center gap-2.5 px-2 text-text-primary">
                    <Folder size={16} aria-hidden="true" className="shrink-0" />
                    <span className="truncate">{g.name}</span>
                  </div>
                ))}
              </>
            ) : null}
          </div>
        </aside>

        {/* Middle: contact list — full width on mobile when no detail */}
        <section
          className={`flex min-h-0 flex-col border-r border-border-default bg-bg-canvas sm:w-[340px] sm:flex-none sm:shrink-0 ${
            mobileDetail ? 'hidden' : 'w-full flex-1'
          }`}
        >
          <header className="flex h-12 items-center gap-1 border-b border-border-default px-3">
            <h2 className="type-body-strong min-w-0 flex-1 truncate text-text-primary">
              {mobile
                ? t('contacts.title')
                : activeBook.kind === 'shared'
                  ? t('contacts.shared')
                  : t('contacts.personal')}
            </h2>
            {canWrite ? (
              <button
                type="button"
                aria-label={t('contacts.new')}
                className="rounded-sm p-1.5 text-text-secondary hover:bg-bg-subtle"
                onClick={() => {
                  setForm(emptyForm());
                  setEditor('create');
                }}
              >
                <UserPlus size={18} />
              </button>
            ) : null}
            {!mobile ? (
              <>
                <button
                  type="button"
                  aria-label={t('contacts.export')}
                  className="rounded-sm p-1.5 text-text-secondary hover:bg-bg-subtle"
                  onClick={() => {
                    window.location.href = exportVcardUrl(activeBook.id);
                  }}
                >
                  <Download size={18} />
                </button>
                {canWrite ? (
                  <button
                    type="button"
                    aria-label={t('contacts.import')}
                    className="rounded-sm p-1.5 text-text-secondary hover:bg-bg-subtle"
                    onClick={() => {
                      setImportError(null);
                      setImportOpen(true);
                    }}
                  >
                    <Upload size={18} />
                  </button>
                ) : null}
                <span className="rounded-sm p-1.5 text-text-tertiary" aria-hidden="true">
                  <MoreHorizontal size={18} />
                </span>
              </>
            ) : null}
          </header>
          <div className="p-2.5">
            <label className="relative block">
              <Search size={16} className="pointer-events-none absolute left-3 top-2.5 text-text-secondary" />
              <input
                type="search"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder={t('contacts.searchPlaceholder')}
                className="type-body h-9 w-full rounded-md border border-transparent bg-bg-muted pl-9 pr-3 text-text-primary placeholder:text-text-tertiary focus:border-brand-primary-500 focus:bg-bg-canvas focus-visible:outline-none"
              />
            </label>
            {mobile ? (
              <div className="mt-2 flex gap-1.5" role="tablist" aria-label={t('contacts.books')}>
                <button
                  type="button"
                  role="tab"
                  aria-selected={bookSlug === 'personal'}
                  className={`type-caption rounded-full px-2.5 py-1 ${
                    bookSlug === 'personal'
                      ? 'bg-brand-primary-600 text-text-on-primary'
                      : 'bg-bg-muted text-text-secondary'
                  }`}
                  onClick={() => navigate('/contacts/personal')}
                >
                  {t('contacts.personalShort')}
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={bookSlug === 'shared'}
                  className={`type-caption rounded-full px-2.5 py-1 ${
                    bookSlug === 'shared'
                      ? 'bg-brand-primary-600 text-text-on-primary'
                      : 'bg-bg-muted text-text-secondary'
                  }`}
                  onClick={() => navigate('/contacts/shared')}
                >
                  {t('contacts.shared')}
                </button>
              </div>
            ) : null}
          </div>
          <ul className="min-h-0 flex-1 overflow-y-auto">
            {empty ? (
              <li className="flex flex-col items-center gap-3 px-6 py-16 text-center" data-testid="contacts-empty">
                <span
                  className="flex size-20 items-center justify-center rounded-full bg-bg-muted text-text-tertiary"
                  aria-hidden="true"
                >
                  <User size={36} strokeWidth={1.5} />
                </span>
                <p className="type-body text-text-secondary">{t('contacts.emptyTitle')}</p>
                <p className="type-small text-text-tertiary">{t('contacts.emptyHint')}</p>
                {canWrite ? (
                  <Button
                    type="button"
                    onClick={() => {
                      setForm(emptyForm());
                      setEditor('create');
                    }}
                  >
                    <Plus size={16} /> {t('contacts.new')}
                  </Button>
                ) : null}
              </li>
            ) : (
              contacts.data?.map((c) => {
                const active = selected?.id === c.id;
                const email = c.emails[0]?.email;
                return (
                  <li key={c.id}>
                    <button
                      type="button"
                      onClick={() => navigate(`/contacts/${bookSlug}/${c.id}`)}
                      className={`flex w-full items-center gap-2.5 border-b border-border-default px-3 py-2 text-left ${
                        active ? 'bg-brand-primary-50' : 'hover:bg-bg-subtle'
                      }`}
                    >
                      <Avatar initials={initialsOf(c.display_name)} seed={c.id} size={32} />
                      <span className="min-w-0 flex-1">
                        <span
                          className={`type-small block truncate ${
                            active ? 'font-semibold text-brand-primary-700' : 'text-text-primary'
                          }`}
                        >
                          {c.display_name}
                        </span>
                        {c.organization || email ? (
                          <span className="type-caption block truncate font-normal text-text-secondary">
                            {[c.organization, email].filter(Boolean).join(' · ')}
                          </span>
                        ) : null}
                      </span>
                    </button>
                  </li>
                );
              })
            )}
          </ul>
        </section>

        {/* Right: detail — full screen on mobile when a contact is open */}
        <section
          className={`min-w-0 flex-col bg-bg-canvas ${
            mobileDetail ? 'flex w-full flex-1' : mobile ? 'hidden' : 'flex min-w-0 flex-1'
          }`}
        >
          {selected ? (
            <>
              <header className="flex h-12 shrink-0 items-center gap-2 border-b border-border-default px-2 sm:px-3">
                {mobile ? (
                  <button
                    type="button"
                    onClick={() => navigate(`/contacts/${bookSlug}`)}
                    aria-label={t('system.back')}
                    className="flex size-11 items-center justify-center rounded-sm text-text-primary hover:bg-bg-subtle"
                  >
                    <ArrowLeft size={22} />
                  </button>
                ) : null}
                <h2 className="type-heading min-w-0 flex-1 truncate sm:hidden">{selected.display_name}</h2>
                {selected.emails[0]?.email ? (
                  <button
                    type="button"
                    aria-label={t('contacts.write')}
                    className="flex size-11 items-center justify-center rounded-sm text-brand-primary-600 hover:bg-bg-subtle sm:hidden"
                    onClick={() => {
                      const email = selected.emails[0]?.email;
                      if (email) navigate(`/compose?to=${encodeURIComponent(email)}`);
                    }}
                  >
                    <Mail size={20} />
                  </button>
                ) : null}
                {selected.phones[0]?.number ? (
                  <a
                    href={`tel:${selected.phones[0].number}`}
                    aria-label={t('contacts.fields.phone')}
                    className="flex size-11 items-center justify-center rounded-sm text-brand-primary-600 hover:bg-bg-subtle sm:hidden"
                  >
                    <Phone size={20} />
                  </a>
                ) : null}
                <div className="hidden flex-1 items-center gap-2 sm:flex">
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => {
                      const email = selected.emails[0]?.email;
                      if (email) navigate(`/compose?to=${encodeURIComponent(email)}`);
                    }}
                  >
                    <SquarePen size={14} /> {t('contacts.write')}
                  </Button>
                  {canWrite ? (
                    <>
                      <Button
                        type="button"
                        variant="secondary"
                        onClick={() => {
                          setForm(toForm(selected));
                          setEditor('edit');
                        }}
                      >
                        <Pencil size={14} /> {t('contacts.edit')}
                      </Button>
                      <button
                        type="button"
                        className="type-label ml-auto inline-flex h-8 items-center gap-1.5 rounded-sm px-2 text-brand-primary-600 hover:bg-bg-subtle disabled:opacity-60"
                        onClick={() => remove.mutate()}
                        disabled={remove.isPending}
                      >
                        <Trash2 size={14} /> {t('contacts.delete')}
                      </button>
                    </>
                  ) : null}
                </div>
              </header>
              <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-6">
                <div className="mb-6 flex items-center gap-4">
                  <Avatar initials={initialsOf(selected.display_name)} seed={selected.id} size={56} />
                  <div>
                    <h2 className="type-title text-text-primary">{selected.display_name}</h2>
                    {selected.organization ? (
                      <p className="type-small text-text-secondary">{selected.organization}</p>
                    ) : null}
                    <span className="type-caption mt-1 inline-block rounded-full bg-bg-muted px-2 py-0.5 text-text-secondary">
                      {activeBook.kind === 'shared' ? t('contacts.shared') : t('contacts.personal')}
                    </span>
                  </div>
                </div>
                <dl className="grid max-w-[560px] grid-cols-[120px_minmax(0,1fr)] gap-x-4 gap-y-2.5">
                  {selected.emails.map((e, i) => (
                    <div key={`${e.email}-${i}`} className="contents">
                      <dt className="type-small text-text-secondary">{t('contacts.fields.email')}</dt>
                      <dd className="type-small min-w-0 text-text-primary">
                        <button
                          type="button"
                          className="text-left text-brand-primary-600 hover:underline"
                          onClick={() => navigate(`/compose?to=${encodeURIComponent(e.email)}`)}
                        >
                          {e.email}
                        </button>
                      </dd>
                    </div>
                  ))}
                  {selected.phones.map((p, i) => (
                    <div key={`${p.number}-${i}`} className="contents">
                      <dt className="type-small text-text-secondary">{t('contacts.fields.phone')}</dt>
                      <dd className="type-small min-w-0 text-text-primary">
                        <a className="text-text-primary hover:underline" href={`tel:${p.number}`}>
                          {p.number}
                        </a>
                      </dd>
                    </div>
                  ))}
                  {selected.organization ? (
                    <div className="contents">
                      <dt className="type-small text-text-secondary">{t('contacts.fields.org')}</dt>
                      <dd className="type-small min-w-0 text-text-primary">{selected.organization}</dd>
                    </div>
                  ) : null}
                  {selected.notes ? (
                    <div className="contents">
                      <dt className="type-small text-text-secondary">{t('contacts.fields.notes')}</dt>
                      <dd className="type-small min-w-0 whitespace-pre-wrap text-text-primary">{selected.notes}</dd>
                    </div>
                  ) : null}
                </dl>
              </div>
            </>
          ) : (
            <div
              className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center"
              data-testid="contacts-pick"
            >
              <span
                className="flex size-20 items-center justify-center rounded-full bg-bg-muted text-text-tertiary"
                aria-hidden="true"
              >
                <User size={36} strokeWidth={1.5} />
              </span>
              <p className="type-heading text-text-primary">{t('contacts.pickOneTitle')}</p>
              <p className="type-small max-w-sm text-text-secondary">{t('contacts.pickOne')}</p>
              {canWrite ? (
                <Button
                  type="button"
                  onClick={() => {
                    setForm(emptyForm());
                    setEditor('create');
                  }}
                >
                  <Plus size={16} /> {t('contacts.new')}
                </Button>
              ) : null}
            </div>
          )}
        </section>
      </div>

      {editor ? (
        <Dialog
          title={editor === 'create' ? t('contacts.new') : t('contacts.edit')}
          width={480}
          onClose={() => setEditor(null)}
          onSubmit={() => save.mutate()}
          footer={
            <>
              <Button type="button" variant="secondary" onClick={() => setEditor(null)}>
                {t('common.cancel')}
              </Button>
              <Button type="submit" disabled={!form.display_name.trim() || save.isPending}>
                {t('contacts.save')}
              </Button>
            </>
          }
        >
          <div className="flex flex-col gap-3">
            <label className="flex flex-col gap-1">
              <span className="type-caption text-text-secondary">{t('contacts.fields.name')}</span>
              <input
                data-autofocus
                value={form.display_name}
                onChange={(e) => setForm({ ...form, display_name: e.target.value })}
                className="type-small h-9 rounded-sm border border-border-default px-2"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="type-caption text-text-secondary">{t('contacts.fields.email')}</span>
              <input
                value={form.emails?.[0]?.email ?? ''}
                onChange={(e) => setForm({ ...form, emails: [{ email: e.target.value, type: 'work' }] })}
                className="type-small h-9 rounded-sm border border-border-default px-2"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="type-caption text-text-secondary">{t('contacts.fields.phone')}</span>
              <input
                value={form.phones?.[0]?.number ?? ''}
                onChange={(e) =>
                  setForm({
                    ...form,
                    phones: e.target.value ? [{ number: e.target.value, type: 'work' }] : [],
                  })
                }
                className="type-small h-9 rounded-sm border border-border-default px-2"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="type-caption text-text-secondary">{t('contacts.fields.org')}</span>
              <input
                value={form.organization ?? ''}
                onChange={(e) => setForm({ ...form, organization: e.target.value })}
                className="type-small h-9 rounded-sm border border-border-default px-2"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="type-caption text-text-secondary">{t('contacts.fields.notes')}</span>
              <textarea
                value={form.notes ?? ''}
                onChange={(e) => setForm({ ...form, notes: e.target.value })}
                rows={3}
                className="type-small rounded-sm border border-border-default px-2 py-1.5"
              />
            </label>
          </div>
        </Dialog>
      ) : null}

      {importOpen ? (
        <Dialog
          title={t('contacts.import')}
          width={440}
          onClose={() => setImportOpen(false)}
          footer={
            <>
              <Button type="button" variant="secondary" onClick={() => setImportOpen(false)}>
                {t('common.cancel')}
              </Button>
              <Button type="button" onClick={() => fileRef.current?.click()} disabled={doImport.isPending}>
                {t('contacts.chooseFile')}
              </Button>
            </>
          }
        >
          <p className="type-small mb-3 text-text-secondary">{t('contacts.importHint')}</p>
          <fieldset className="mb-3 flex flex-col gap-2">
            <legend className="type-caption text-text-tertiary">{t('contacts.onDuplicate')}</legend>
            <label className="type-small flex items-center gap-2">
              <input type="radio" name="dup" checked={onDuplicate === 'skip'} onChange={() => setOnDuplicate('skip')} />
              {t('contacts.skipDup')}
            </label>
            <label className="type-small flex items-center gap-2">
              <input
                type="radio"
                name="dup"
                checked={onDuplicate === 'merge'}
                onChange={() => setOnDuplicate('merge')}
              />
              {t('contacts.mergeDup')}
            </label>
          </fieldset>
          {importError ? <p className="type-small text-danger-600">{importError}</p> : null}
          <input
            ref={fileRef}
            type="file"
            accept=".vcf,text/vcard,text/x-vcard"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) doImport.mutate(file);
              e.target.value = '';
            }}
          />
        </Dialog>
      ) : null}
    </AppShell>
  );
}
