import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, Mail, Search } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';

import { Button } from '../../components/Button';
import { AppShell } from '../../components/shell/AppShell';
import { MOBILE_QUERY, useMediaQuery } from '../../lib/useMediaQuery';
import { formatMailDate } from '../mail/formatMailDate';
import { runSearch, searchKey, type SearchField, type SearchScope } from './searchApi';

const RECENT_KEY = 'sm.search.recent';
const MAX_RECENT = 8;

function loadRecent(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === 'string').slice(0, MAX_RECENT) : [];
  } catch {
    return [];
  }
}

function pushRecent(q: string) {
  const clean = q.trim();
  if (!clean) return;
  const next = [clean, ...loadRecent().filter((x) => x.toLowerCase() !== clean.toLowerCase())].slice(0, MAX_RECENT);
  localStorage.setItem(RECENT_KEY, JSON.stringify(next));
}

const SCOPES: SearchScope[] = ['current', 'subfolders', 'all'];
const FIELDS: { id: SearchField; labelKey: string }[] = [
  { id: 'full', labelKey: 'search.fields.full' },
  { id: 'subject', labelKey: 'search.fields.subject' },
  { id: 'from', labelKey: 'search.fields.from' },
  { id: 'to', labelKey: 'search.fields.to' },
  { id: 'cc', labelKey: 'search.fields.cc' },
  { id: 'body', labelKey: 'search.fields.body' },
];

function formatSkDate(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleDateString('sk-SK', { day: 'numeric', month: 'numeric', year: 'numeric' });
}

/** W10 / M8 Hľadanie — Roundcube scope/fields; mobile full-screen with recent (SCREENS_SPEC). */
export function ScreenW10() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const mobile = useMediaQuery(MOBILE_QUERY);
  const [params, setParams] = useSearchParams();
  const qParam = params.get('q') ?? '';
  const [draft, setDraft] = useState(qParam);
  const [recent] = useState(loadRecent);
  const scope = (params.get('scope') as SearchScope) || 'all';
  const field = (params.get('field') as SearchField) || 'full';
  const folderId = params.get('folder_id') ?? undefined;
  const mailbox = params.get('mailbox') ?? 'default';

  const enabled = qParam.trim().length > 0;
  const result = useQuery({
    queryKey: searchKey({ q: qParam, scope, fields: [field], folder_id: folderId, mailbox }),
    queryFn: () => runSearch({ q: qParam, scope, fields: [field], folder_id: folderId, mailbox }),
    enabled,
  });

  // Telo / Celá správa: then also on the IMAP server — bodies of unopened messages are not indexed locally (#38)
  const askServer = enabled && (field === 'body' || field === 'full') && result.isSuccess;
  const serverResult = useQuery({
    queryKey: searchKey({ q: qParam, scope, fields: [field], folder_id: folderId, mailbox, server: true }),
    queryFn: () => runSearch({ q: qParam, scope, fields: [field], folder_id: folderId, mailbox, server: true }),
    enabled: askServer,
    retry: false,
  });
  const shown = serverResult.data ?? result.data;
  const serverState = serverResult.isError ? 'unavailable' : serverResult.data?.server_search;

  const oldestLabel = useMemo(
    () => formatSkDate(result.data?.oldest_downloaded_at ?? null),
    [result.data?.oldest_downloaded_at],
  );

  function applyQuery(next: string) {
    const clean = next.trim();
    if (clean) pushRecent(clean);
    const nextParams = new URLSearchParams(params);
    if (clean) nextParams.set('q', clean);
    else nextParams.delete('q');
    setParams(nextParams, { replace: true });
  }

  function setScope(s: SearchScope) {
    const next = new URLSearchParams(params);
    next.set('scope', s);
    setParams(next, { replace: true });
  }

  function setField(f: SearchField) {
    const next = new URLSearchParams(params);
    next.set('field', f);
    setParams(next, { replace: true });
  }

  const messages = shown?.messages ?? [];
  const empty = enabled && result.isSuccess && !serverResult.isFetching && messages.length === 0;

  return (
    <AppShell section="mail">
      <div className="flex min-h-0 min-w-0 flex-1 flex-col bg-bg-canvas" data-testid={mobile ? 'screen-m8' : undefined}>
        <header className="flex shrink-0 flex-col gap-3 border-b border-border-default px-4 py-3">
          <div className="flex items-center gap-2">
            {mobile ? (
              <button
                type="button"
                onClick={() => navigate(-1)}
                aria-label={t('system.back')}
                className="flex size-11 shrink-0 items-center justify-center rounded-sm text-text-primary hover:bg-bg-subtle"
              >
                <ArrowLeft size={22} />
              </button>
            ) : null}
            <h1 className="type-heading text-text-primary">{t('search.title')}</h1>
            {oldestLabel ? (
              <p className="type-caption text-text-tertiary" data-testid="search-corpus-banner">
                {t('search.corpusFrom', { date: oldestLabel })}
              </p>
            ) : null}
          </div>
          <label className="relative block max-w-2xl">
            <Search size={18} className="pointer-events-none absolute left-3 top-[11px] text-text-secondary" />
            <input
              type="search"
              value={draft}
              autoFocus={mobile}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') applyQuery(draft);
              }}
              placeholder={t('search.placeholder')}
              className="type-body h-10 w-full rounded-md border border-border-strong bg-bg-canvas pl-10 pr-3 text-text-primary placeholder:text-text-tertiary focus:border-brand-primary-500 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-1 focus-visible:outline-brand-primary-500"
              aria-label={t('search.title')}
            />
          </label>
          <div className="flex flex-wrap items-center gap-4">
            <fieldset className="flex flex-wrap items-center gap-2">
              <legend className="type-caption sr-only">{t('search.scopeLabel')}</legend>
              {SCOPES.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setScope(s)}
                  aria-pressed={scope === s}
                  className={`type-caption inline-flex h-6 items-center rounded-full border px-2.5 ${
                    scope === s
                      ? 'border-brand-primary-600 bg-brand-primary-600 text-text-on-primary'
                      : 'border-border-default bg-bg-canvas text-text-primary hover:bg-bg-subtle'
                  }`}
                >
                  {t(`search.scope.${s}`)}
                </button>
              ))}
            </fieldset>
            <fieldset className="flex flex-wrap items-center gap-2">
              <legend className="type-caption sr-only">{t('search.fieldLabel')}</legend>
              {FIELDS.map((f) => (
                <button
                  key={f.id}
                  type="button"
                  onClick={() => setField(f.id)}
                  aria-pressed={field === f.id}
                  className={`type-caption inline-flex h-6 items-center rounded-full border px-2.5 ${
                    field === f.id
                      ? 'border-brand-primary-400 bg-brand-primary-50 text-brand-primary-700'
                      : 'border-border-default bg-bg-canvas text-text-primary hover:bg-bg-subtle'
                  }`}
                >
                  {t(f.labelKey)}
                </button>
              ))}
            </fieldset>
          </div>
        </header>
        {askServer && serverResult.isFetching ? (
          <p role="status" className="type-small px-4 pt-3 text-text-secondary sm:px-6" data-testid="search-server">
            {t('search.serverSearching')}
          </p>
        ) : serverState && serverState !== 'ok' ? (
          <p role="status" className="type-small px-4 pt-3 text-warning-700 sm:px-6" data-testid="search-server">
            {t(
              serverState === 'busy'
                ? 'search.serverBusy'
                : serverState === 'partial'
                  ? 'search.serverPartial'
                  : 'search.serverUnavailable',
            )}
          </p>
        ) : null}

        <div className="min-h-0 flex-1 overflow-y-auto">
          {!enabled ? (
            mobile && recent.length > 0 ? (
              <div className="p-4" data-testid="search-recent">
                <p className="type-caption mb-2 text-text-tertiary">{t('search.recent')}</p>
                <ul className="divide-y divide-border-default rounded-sm border border-border-default">
                  {recent.map((q) => (
                    <li key={q}>
                      <button
                        type="button"
                        className="type-body flex w-full items-center gap-2 px-3 py-3 text-left text-text-primary hover:bg-bg-subtle"
                        onClick={() => {
                          setDraft(q);
                          applyQuery(q);
                        }}
                      >
                        <Search size={16} className="text-text-tertiary" aria-hidden="true" />
                        {q}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <p className="type-body p-8 text-text-tertiary">{t('search.typeHint')}</p>
            )
          ) : result.isLoading ? (
            <p className="type-body p-8 text-text-tertiary" aria-busy="true">
              {t('search.loading')}
            </p>
          ) : empty ? (
            <div className="flex flex-col items-center gap-3 px-6 py-20 text-center" data-testid="search-empty">
              <span
                className="flex size-20 items-center justify-center rounded-full bg-bg-muted text-text-tertiary"
                aria-hidden="true"
              >
                <Search size={36} strokeWidth={1.5} />
              </span>
              <p className="type-heading text-text-primary">{t('search.emptyTitle')}</p>
              <p className="type-small max-w-md text-text-secondary">{t('search.emptyHint')}</p>
              <p className="type-caption max-w-md text-text-tertiary">{t('search.emptyTips')}</p>
              {scope !== 'all' ? (
                <Button type="button" onClick={() => setScope('all')}>
                  {t('search.searchAllMailboxes')}
                </Button>
              ) : null}
            </div>
          ) : (
            <section className="m-4 overflow-hidden rounded-md border border-border-default sm:mx-6">
              <h2 className="type-heading flex h-11 items-center border-b border-border-default px-3.5 text-text-primary">
                {t('search.emailsGroup', { count: shown?.total ?? 0 })}
              </h2>
              <ul className="divide-y divide-border-default">
                {messages.map((m) => (
                  <li key={m.id} className="flex items-start gap-3 px-3.5 py-2.5 hover:bg-bg-subtle">
                    <Mail size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-text-secondary" />
                    <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                      <span className="type-small min-w-0 truncate text-text-primary">
                        {m.from_name ? <span className="font-semibold">{m.from_name}</span> : null}
                        {m.from_email ? (
                          <>
                            {m.from_name ? ' ' : null}
                            <button
                              type="button"
                              className="text-text-secondary hover:text-brand-primary-600 hover:underline"
                              onClick={() => {
                                const email = m.from_email;
                                if (email) navigate(`/compose?to=${encodeURIComponent(email)}`);
                              }}
                            >
                              {m.from_email}
                            </button>
                          </>
                        ) : !m.from_name ? (
                          '—'
                        ) : null}
                        {' · '}
                        <Link
                          to={`/mail/${encodeURIComponent(mailbox)}/inbox/${encodeURIComponent(m.id)}`}
                          className="text-text-primary hover:underline"
                          onClick={(e) => {
                            e.preventDefault();
                            navigate(`/mail/${encodeURIComponent(mailbox)}/inbox/${encodeURIComponent(m.id)}`);
                          }}
                        >
                          {m.subject || t('search.noSubject')}
                        </Link>
                      </span>
                      {m.preview ? (
                        <span className="type-caption line-clamp-2 font-normal text-text-secondary">{m.preview}</span>
                      ) : null}
                    </div>
                    {m.received_at ? (
                      <span className="type-caption shrink-0 font-normal text-text-secondary">
                        {formatMailDate(m.received_at)}
                      </span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      </div>
    </AppShell>
  );
}
