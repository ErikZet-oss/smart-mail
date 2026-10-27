import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Download, MoreHorizontal, Pencil, Plus, Search, Trash2, Upload, UserPlus } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Navigate, useNavigate, useParams } from 'react-router-dom';

import { Avatar } from '../../components/Avatar';
import { Button } from '../../components/Button';
import { Dialog } from '../../components/Dialog';
import { AppShell } from '../../components/shell/AppShell';
import { useToasts } from '../../components/toastContext';
import { ApiError } from '../../lib/api';
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

/** W9 Kontakty — Osobné / Zdieľané books, list, detail, import (SCREENS_SPEC W9; Figma 59:47915). */
export function ScreenW9() {
  const { t } = useTranslation();
  const navigate = useNavigate();
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

  const selected = useMemo(
    () => contacts.data?.find((c) => c.id === contactId) ?? contacts.data?.[0] ?? null,
    [contacts.data, contactId],
  );

  useEffect(() => {
    if (!activeBook || !contacts.data?.length) return;
    if (contactId && contacts.data.some((c) => c.id === contactId)) return;
    if (contacts.data[0] && !contactId) {
      navigate(`/contacts/${bookParam ?? activeBook.kind}/${contacts.data[0].id}`, { replace: true });
    }
  }, [contacts.data, contactId, activeBook, bookParam, navigate]);

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
          <p className="type-body text-danger-700">{t('contacts.errors.load')}</p>
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

  return (
    <AppShell section="contacts">
      <div className="flex min-h-0 min-w-0 flex-1">
        {/* Left: address books + groups */}
        <aside className="flex w-60 shrink-0 flex-col border-r border-border-default bg-bg-canvas">
          <header className="flex h-12 items-center justify-between border-b border-border-default px-3">
            <h1 className="type-heading text-text-primary">{t('contacts.title')}</h1>
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            <p className="type-caption px-2 py-1 text-text-tertiary">{t('contacts.books')}</p>
            {books.data.map((b) => {
              const slug = b.kind === 'shared' ? 'shared' : 'personal';
              const active = activeBook.id === b.id;
              return (
                <button
                  key={b.id}
                  type="button"
                  onClick={() => navigate(`/contacts/${slug}`)}
                  className={`type-small flex w-full items-center justify-between rounded-sm px-2 py-1.5 text-left ${
                    active ? 'bg-brand-primary-50 text-brand-primary-800' : 'text-text-primary hover:bg-bg-subtle'
                  }`}
                >
                  <span className="truncate">
                    {b.kind === 'shared' ? t('contacts.shared') : t('contacts.personal')}
                  </span>
                </button>
              );
            })}
            <p className="type-caption mt-3 px-2 py-1 text-text-tertiary">{t('contacts.stubs')}</p>
            <div className="type-small px-2 py-1.5 text-text-tertiary" title={t('common.comingSoon')}>
              {t('contacts.moneyBook')}
            </div>
            <div className="type-small px-2 py-1.5 text-text-tertiary" title={t('common.comingSoon')}>
              {t('contacts.recent')}
            </div>
            {(groups.data?.length ?? 0) > 0 ? (
              <>
                <p className="type-caption mt-3 px-2 py-1 text-text-tertiary">{t('contacts.groups')}</p>
                {groups.data?.map((g) => (
                  <div key={g.id} className="type-small truncate px-2 py-1.5 text-text-secondary">
                    {g.name}
                  </div>
                ))}
              </>
            ) : null}
          </div>
        </aside>

        {/* Middle: contact list */}
        <section className="flex w-80 shrink-0 flex-col border-r border-border-default bg-bg-canvas">
          <header className="flex h-12 items-center gap-1 border-b border-border-default px-2">
            <h2 className="type-heading min-w-0 flex-1 truncate text-text-primary">
              {activeBook.kind === 'shared' ? t('contacts.shared') : t('contacts.personal')}
            </h2>
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
            <span className="rounded-sm p-1.5 text-text-tertiary" aria-hidden="true">
              <MoreHorizontal size={18} />
            </span>
          </header>
          <div className="border-b border-border-default p-2">
            <label className="relative block">
              <Search size={14} className="pointer-events-none absolute left-2.5 top-2.5 text-text-tertiary" />
              <input
                type="search"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder={t('contacts.searchPlaceholder')}
                className="type-small h-9 w-full rounded-sm border border-border-default bg-bg-canvas pl-8 pr-3 text-text-primary placeholder:text-text-tertiary focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-1 focus-visible:outline-brand-primary-500"
              />
            </label>
          </div>
          <ul className="min-h-0 flex-1 overflow-y-auto">
            {empty ? (
              <li className="flex flex-col items-center gap-3 px-6 py-16 text-center">
                <p className="type-body text-text-secondary">{t('contacts.emptyTitle')}</p>
                <p className="type-small text-text-tertiary">{t('contacts.emptyHint')}</p>
                <Button
                  type="button"
                  onClick={() => {
                    setForm(emptyForm());
                    setEditor('create');
                  }}
                >
                  <Plus size={16} /> {t('contacts.new')}
                </Button>
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
                      className={`flex w-full items-start gap-2.5 border-b border-border-subtle px-3 py-2.5 text-left ${
                        active ? 'bg-brand-primary-50' : 'hover:bg-bg-subtle'
                      }`}
                    >
                      <Avatar initials={initialsOf(c.display_name)} seed={c.id} size={32} />
                      <span className="min-w-0 flex-1">
                        <span className="type-small block truncate font-medium text-text-primary">
                          {c.display_name}
                        </span>
                        {c.organization ? (
                          <span className="type-caption block truncate text-text-secondary">{c.organization}</span>
                        ) : null}
                        {email ? <span className="type-caption block truncate text-text-tertiary">{email}</span> : null}
                      </span>
                    </button>
                  </li>
                );
              })
            )}
          </ul>
        </section>

        {/* Right: detail */}
        <section className="flex min-w-0 flex-1 flex-col bg-bg-canvas">
          {selected ? (
            <>
              <header className="flex h-12 shrink-0 items-center gap-2 border-b border-border-default px-3">
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => {
                    const email = selected.emails[0]?.email;
                    if (email) navigate(`/compose?to=${encodeURIComponent(email)}`);
                  }}
                >
                  {t('contacts.write')}
                </Button>
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
                <Button type="button" variant="secondary" onClick={() => remove.mutate()} disabled={remove.isPending}>
                  <Trash2 size={14} /> {t('contacts.delete')}
                </Button>
              </header>
              <div className="min-h-0 flex-1 overflow-y-auto p-6">
                <div className="mb-6 flex items-center gap-4">
                  <Avatar initials={initialsOf(selected.display_name)} seed={selected.id} size={56} />
                  <div>
                    <h2 className="type-title text-text-primary">{selected.display_name}</h2>
                    {selected.organization ? (
                      <p className="type-small text-text-secondary">{selected.organization}</p>
                    ) : null}
                    <span className="type-caption mt-1 inline-block rounded-sm bg-bg-muted px-2 py-0.5 text-text-secondary">
                      {activeBook.kind === 'shared' ? t('contacts.shared') : t('contacts.personal')}
                    </span>
                  </div>
                </div>
                <dl className="grid max-w-xl gap-3">
                  {selected.emails.map((e, i) => (
                    <div key={`${e.email}-${i}`}>
                      <dt className="type-caption text-text-tertiary">{t('contacts.fields.email')}</dt>
                      <dd className="type-body text-text-primary">{e.email}</dd>
                    </div>
                  ))}
                  {selected.phones.map((p, i) => (
                    <div key={`${p.number}-${i}`}>
                      <dt className="type-caption text-text-tertiary">{t('contacts.fields.phone')}</dt>
                      <dd className="type-body text-text-primary">{p.number}</dd>
                    </div>
                  ))}
                  {selected.organization ? (
                    <div>
                      <dt className="type-caption text-text-tertiary">{t('contacts.fields.org')}</dt>
                      <dd className="type-body text-text-primary">{selected.organization}</dd>
                    </div>
                  ) : null}
                  {selected.notes ? (
                    <div>
                      <dt className="type-caption text-text-tertiary">{t('contacts.fields.notes')}</dt>
                      <dd className="type-body whitespace-pre-wrap text-text-primary">{selected.notes}</dd>
                    </div>
                  ) : null}
                </dl>
              </div>
            </>
          ) : (
            <div className="flex flex-1 items-center justify-center p-8">
              <p className="type-body text-text-tertiary">{t('contacts.pickOne')}</p>
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
          {importError ? <p className="type-small text-danger-700">{importError}</p> : null}
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
