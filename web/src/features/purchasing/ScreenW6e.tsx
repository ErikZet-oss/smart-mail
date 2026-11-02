import { useQuery } from '@tanstack/react-query';
import { FileText, Search } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, Navigate, useNavigate } from 'react-router-dom';

import { Banner } from '../../components/Banner';
import { AppShell } from '../../components/shell/AppShell';
import { MOBILE_QUERY, useMediaQuery } from '../../lib/useMediaQuery';
import { fetchMe } from '../auth/authApi';
import { DocsHeader } from '../money/DocsHeader';
import { UPLOAD_ROLES } from '../money/docsAccess';
import { day, money } from '../money/moneyApi';
import { useFeaturesState } from '../system/features';
import { documentsKey, fetchDocuments, type DocumentFilter, type SupplierDocument } from './purchasingApi';

const STATUS_TONE: Record<SupplierDocument['status'], string> = {
  extracting: 'bg-bg-muted text-text-secondary',
  needs_review: 'bg-bg-muted text-text-secondary',
  missing_data: 'bg-warning-50 text-warning-700',
  duplicate: 'bg-bg-muted text-text-secondary',
  unreadable: 'bg-danger-50 text-danger-600',
  failed: 'bg-danger-50 text-danger-600',
  ignored: 'bg-bg-muted text-text-tertiary',
};
const FILTERS: DocumentFilter[] = ['open', 'all', 'duplicate', 'ignored'];

/**
 * W6e Dodacie listy prijaté – zoznam (Figma `46:41526`, M13 `85:3245`). Phase 4a: supplier documents read from mail
 * or uploaded, before matching (4b) and before any Money write (4c) — so „Číslo dokladu“ is „nový – návrh“ and
 * „Sklad. pohybu“ is „pri zápise“ (D13). Roles: warehouse, accounting, admin.
 */
export function ScreenW6e() {
  const { t } = useTranslation();
  const features = useFeaturesState();
  const mobile = useMediaQuery(MOBILE_QUERY);
  const navigate = useNavigate();
  const me = useQuery({ queryKey: ['me'], queryFn: fetchMe, retry: false });
  const allowed = UPLOAD_ROLES.has(me.data?.person?.role ?? '');
  const [status, setStatus] = useState<DocumentFilter>('open');
  const [q, setQ] = useState('');
  const [page, setPage] = useState(1);
  const list = useQuery({
    queryKey: documentsKey(status, q, page),
    queryFn: () => fetchDocuments(status, q, page),
    enabled: features.money && allowed,
    retry: false,
  });
  if (features.loaded && !features.money) return <Navigate to="/404" replace />;
  const items = list.data?.items ?? [];
  const total = list.data?.total ?? 0;
  const statusLabel = (d: SupplierDocument) => t(`purchasing.status.${d.status}`);
  return (
    <AppShell section="documents">
      <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto bg-bg-canvas" data-testid="screen-w6e">
        <DocsHeader active="delivery-notes" counts={{ 'delivery-notes': status === 'open' ? total : undefined }} />
        <div className="flex flex-col gap-4 p-4 md:p-6">
          {!features.loaded || !me.data ? null : !allowed ? (
            <Banner kind="info" message={t('purchasing.roleOnly')} />
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <label className="relative min-w-0 flex-1 basis-60">
                  <Search size={16} aria-hidden="true" className="absolute left-3 top-2.5 text-text-tertiary" />
                  <input
                    value={q}
                    onChange={(e) => {
                      setQ(e.target.value);
                      setPage(1);
                    }}
                    placeholder={t('purchasing.search')}
                    aria-label={t('purchasing.search')}
                    className="type-body h-9 w-full rounded-md border border-transparent bg-bg-muted pl-9 pr-3 text-text-primary placeholder:text-text-tertiary focus:border-brand-primary-500 focus:bg-bg-canvas"
                  />
                </label>
                <select
                  aria-label={t('purchasing.filter')}
                  value={status}
                  onChange={(e) => {
                    setStatus(e.target.value as DocumentFilter);
                    setPage(1);
                  }}
                  className="type-body h-9 rounded-sm border border-border-default bg-bg-canvas px-2"
                >
                  {FILTERS.map((f) => (
                    <option key={f} value={f}>
                      {t(`purchasing.filters.${f}`)}
                    </option>
                  ))}
                </select>
              </div>
              {list.isError ? (
                <Banner kind="warning" message={t('mail.errors.generic')} />
              ) : items.length === 0 && !list.isLoading ? (
                <div className="flex flex-col items-center gap-2 py-12 text-center text-text-secondary">
                  <FileText size={22} aria-hidden="true" />
                  <p className="type-body">{t('purchasing.empty')}</p>
                </div>
              ) : mobile ? (
                <ul className="flex flex-col gap-2" data-testid="documents-list">
                  {items.map((d) => (
                    <li key={d.id}>
                      <Link
                        to={`/docs/delivery-notes/${d.id}`}
                        className="type-small flex flex-col gap-1 rounded-md border border-border-default p-3"
                      >
                        <div className="flex items-start gap-2">
                          <span className="type-label min-w-0 flex-1 break-words text-text-primary">
                            {d.supplier_name ?? d.filename}
                          </span>
                          <StatusChip tone={STATUS_TONE[d.status]} label={statusLabel(d)} />
                        </div>
                        <span className="break-all text-text-secondary">
                          {d.doc_number ?? '–'} · {day(d.doc_date)}
                        </span>
                        <span className="text-text-secondary">
                          {t('purchasing.linesCount', { count: d.lines })}
                          {d.total ? ` · ${money(d.total)}` : ''}
                          {d.branch_name ? ` · ${d.branch_name}` : ''}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="overflow-x-auto rounded-md border border-border-default">
                  <table
                    className="type-small w-full min-w-[960px] text-left text-text-primary"
                    data-testid="documents-list"
                  >
                    <thead className="bg-bg-subtle text-text-secondary">
                      <tr>
                        {(
                          [
                            'number',
                            'received',
                            'supplier',
                            'issued',
                            'moved',
                            'centre',
                            'warehouse',
                            'lines',
                            'total',
                            'status',
                            'branch',
                          ] as const
                        ).map((c) => (
                          <th
                            key={c}
                            className={`px-3 py-2 font-normal ${c === 'lines' || c === 'total' ? 'text-right' : ''}`}
                          >
                            {t(`purchasing.cols.${c}`)}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((d) => (
                        <tr
                          key={d.id}
                          tabIndex={0}
                          data-testid={`document-row-${d.id}`}
                          onClick={() => navigate(`/docs/delivery-notes/${d.id}`)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') navigate(`/docs/delivery-notes/${d.id}`);
                          }}
                          className="cursor-pointer border-t border-border-default hover:bg-bg-subtle"
                        >
                          <td className="px-3 py-2 text-text-tertiary">{t('purchasing.newDraft')}</td>
                          <td className="px-3 py-2">{d.doc_number ?? '–'}</td>
                          <td className="px-3 py-2">{d.supplier_name ?? d.filename}</td>
                          <td className="px-3 py-2">{day(d.doc_date)}</td>
                          <td className="px-3 py-2 text-text-tertiary">{t('purchasing.onWrite')}</td>
                          <td className="px-3 py-2">{d.centre_code ?? '–'}</td>
                          <td className="px-3 py-2">{d.warehouse_code ?? '–'}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{d.lines}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{d.total ? money(d.total) : '–'}</td>
                          <td className="px-3 py-2">
                            <StatusChip tone={STATUS_TONE[d.status]} label={statusLabel(d)} />
                          </td>
                          <td className="px-3 py-2">{d.branch_name ?? '–'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {total > items.length || page > 1 ? (
                <div className="type-caption flex items-center justify-between text-text-secondary">
                  <span>{t('purchasing.range', { count: items.length, total })}</span>
                  <span className="flex gap-2">
                    <button type="button" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                      ‹
                    </button>
                    <button type="button" disabled={page * 50 >= total} onClick={() => setPage((p) => p + 1)}>
                      ›
                    </button>
                  </span>
                </div>
              ) : null}
            </>
          )}
        </div>
      </main>
    </AppShell>
  );
}

function StatusChip({ tone, label }: { tone: string; label: string }) {
  return (
    <span className={`type-caption inline-flex h-5 shrink-0 items-center rounded-full px-2 ${tone}`}>{label}</span>
  );
}
