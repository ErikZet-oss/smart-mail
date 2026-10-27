import { useQuery } from '@tanstack/react-query';
import { Search } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';

import { AppShell } from '../../components/shell/AppShell';
import { runSearch, searchKey, type SearchField, type SearchScope } from './searchApi';

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

/** W10 Hľadanie — Roundcube scope/fields, results + empty (SCREENS_SPEC W10; Figma 61:49657 / 61:50001). */
export function ScreenW10() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const qParam = params.get('q') ?? '';
  const [draft, setDraft] = useState(qParam);
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

  const oldestLabel = useMemo(
    () => formatSkDate(result.data?.oldest_downloaded_at ?? null),
    [result.data?.oldest_downloaded_at],
  );

  function applyQuery(next: string) {
    const clean = next.trim();
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

  const messages = result.data?.messages ?? [];
  const empty = enabled && result.isSuccess && messages.length === 0;

  return (
    <AppShell section="mail">
      <div className="flex min-h-0 min-w-0 flex-1 flex-col bg-bg-canvas">
        <header className="flex shrink-0 flex-col gap-3 border-b border-border-default px-4 py-3">
          <div className="flex items-center gap-3">
            <h1 className="type-heading text-text-primary">{t('search.title')}</h1>
            {oldestLabel ? (
              <p className="type-caption text-text-tertiary" data-testid="search-corpus-banner">
                {t('search.corpusFrom', { date: oldestLabel })}
              </p>
            ) : null}
          </div>
          <label className="relative block max-w-2xl">
            <Search size={16} className="pointer-events-none absolute left-3 top-2.5 text-text-tertiary" />
            <input
              type="search"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') applyQuery(draft);
              }}
              placeholder={t('search.placeholder')}
              className="type-body h-10 w-full rounded-sm border border-border-default bg-bg-canvas pl-10 pr-3 text-text-primary placeholder:text-text-tertiary focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-1 focus-visible:outline-brand-primary-500"
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
                  className={`type-caption rounded-full px-2.5 py-1 ${
                    scope === s
                      ? 'bg-brand-primary-600 text-text-on-primary'
                      : 'bg-bg-muted text-text-secondary hover:bg-bg-subtle'
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
                  className={`type-caption rounded-full px-2.5 py-1 ${
                    field === f.id
                      ? 'bg-brand-primary-50 text-brand-primary-800 ring-1 ring-brand-primary-300'
                      : 'bg-bg-muted text-text-secondary hover:bg-bg-subtle'
                  }`}
                >
                  {t(f.labelKey)}
                </button>
              ))}
            </fieldset>
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {!enabled ? (
            <p className="type-body p-8 text-text-tertiary">{t('search.typeHint')}</p>
          ) : result.isLoading ? (
            <p className="type-body p-8 text-text-tertiary" aria-busy="true">
              {t('search.loading')}
            </p>
          ) : empty ? (
            <div className="flex flex-col items-center gap-3 px-6 py-20 text-center" data-testid="search-empty">
              <p className="type-heading text-text-primary">{t('search.emptyTitle')}</p>
              <p className="type-small max-w-md text-text-secondary">{t('search.emptyHint')}</p>
            </div>
          ) : (
            <ul className="divide-y divide-border-subtle">
              <li className="type-caption bg-bg-subtle px-4 py-2 text-text-secondary">
                {t('search.emailsGroup', { count: result.data?.total ?? 0 })}
              </li>
              {messages.map((m) => (
                <li key={m.id}>
                  <Link
                    to={`/mail/${encodeURIComponent(mailbox)}/inbox/${encodeURIComponent(m.id)}`}
                    className="flex flex-col gap-0.5 px-4 py-3 hover:bg-bg-subtle"
                    onClick={(e) => {
                      e.preventDefault();
                      navigate(`/mail/${encodeURIComponent(mailbox)}/inbox/${encodeURIComponent(m.id)}`);
                    }}
                  >
                    <span className="type-small font-medium text-text-primary">
                      {m.subject || t('search.noSubject')}
                    </span>
                    <span className="type-caption text-text-secondary">
                      {m.from_name || m.from_email || '—'}
                      {m.from_email && m.from_name ? ` · ${m.from_email}` : ''}
                    </span>
                    {m.preview ? (
                      <span className="type-caption line-clamp-2 text-text-tertiary">{m.preview}</span>
                    ) : null}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </AppShell>
  );
}
