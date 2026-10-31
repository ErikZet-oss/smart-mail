import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { BellRing, CircleAlert, FileText } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, Navigate } from 'react-router-dom';

import { Banner } from '../../components/Banner';
import { Button } from '../../components/Button';
import { AppShell } from '../../components/shell/AppShell';
import { ApiError } from '../../lib/api';
import { fetchMe } from '../auth/authApi';
import { useFeaturesState } from '../system/features';
import {
  day,
  debtorsKey,
  fetchDebtors,
  fetchReminderHistory,
  money,
  prepareReminders,
  reminderHistoryKey,
  type ReminderResult,
  type ReminderTone,
} from './moneyApi';

const ROLES = new Set(['admin', 'sales', 'accounting']);

/**
 * W8b Upomienky (Phase 3e, SCREENS_SPEC): customers with overdue invoices → „Pripraviť upomienky“ → one draft per
 * customer in Koncepty (E2 table + Money PDFs) → the person opens, checks and sends each. History „Odoslané upomienky“.
 * No change of reminder dates in Money (MONEY_API §5.2). Only with FEATURE_MONEY; accounting, sales, admin.
 */
export function ScreenW8b() {
  const { t } = useTranslation();
  const features = useFeaturesState();
  const me = useQuery({ queryKey: ['me'], queryFn: fetchMe, retry: false });
  const [tab, setTab] = useState<'open' | 'history'>('open');
  const allowed = ROLES.has(me.data?.person?.role ?? '');
  if (features.loaded && !features.money) return <Navigate to="/404" replace />;
  return (
    <AppShell section="documents">
      <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto bg-bg-canvas" data-testid="screen-w8b">
        <header className="flex flex-col gap-3 border-b border-border-default px-4 pt-4 md:px-6">
          <h1 className="type-title text-text-primary">{t('reminders.title')}</h1>
          <div role="tablist" aria-label={t('reminders.title')} className="flex gap-4">
            {(['open', 'history'] as const).map((id) => (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={tab === id}
                onClick={() => setTab(id)}
                className={`type-label h-10 border-b-2 ${
                  tab === id
                    ? 'border-brand-primary-600 text-brand-primary-700'
                    : 'border-transparent text-text-secondary'
                }`}
              >
                {t(`reminders.tabs.${id}`)}
              </button>
            ))}
          </div>
        </header>
        <div className="flex flex-col gap-4 p-4 md:p-6">
          {!features.loaded || !me.data ? null : !allowed ? (
            <Banner kind="info" message={t('reminders.roleOnly')} />
          ) : tab === 'open' ? (
            <OpenTab />
          ) : (
            <HistoryTab />
          )}
        </div>
      </main>
    </AppShell>
  );
}

function OpenTab() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const debtors = useQuery({ queryKey: debtorsKey, queryFn: fetchDebtors, retry: false });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [tone, setTone] = useState<ReminderTone>('polite');
  const [results, setResults] = useState<ReminderResult[] | null>(null);
  const prepare = useMutation({
    mutationFn: () => prepareReminders([...selected], tone),
    onSuccess: (out) => {
      setResults(out);
      setSelected(new Set());
      void qc.invalidateQueries({ queryKey: debtorsKey });
      void qc.invalidateQueries({ queryKey: reminderHistoryKey });
    },
  });
  const rows = debtors.data ?? [];
  const names = new Map(rows.map((d) => [d.company.money_id, d.company.name]));
  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  if (debtors.isPending) {
    return (
      <div aria-busy="true" aria-label={t('reminders.loading')} className="flex flex-col gap-2">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="h-10 animate-pulse rounded-sm bg-bg-muted" />
        ))}
      </div>
    );
  }
  if (debtors.isError) {
    const code = debtors.error instanceof ApiError ? debtors.error.detail.code : 'generic';
    return (
      <Banner
        kind="warning"
        message={t(`reminders.errors.${code}`, { defaultValue: t('reminders.errors.money_unavailable') })}
        action={{ label: t('reminders.retry'), onClick: () => void debtors.refetch() }}
      />
    );
  }
  return (
    <>
      {results ? <Results results={results} names={names} /> : null}
      {rows.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-16 text-center" data-testid="reminders-empty">
          <BellRing size={32} aria-hidden="true" className="text-text-tertiary" />
          <p className="type-heading text-text-primary">{t('reminders.emptyTitle')}</p>
          <p className="type-body text-text-secondary">{t('reminders.emptyText')}</p>
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <div
              role="radiogroup"
              aria-label={t('reminders.tone')}
              className="inline-flex rounded-sm border border-border-default"
            >
              {(['polite', 'firm'] as const).map((id) => (
                <button
                  key={id}
                  type="button"
                  role="radio"
                  aria-checked={tone === id}
                  onClick={() => setTone(id)}
                  className={`type-label h-9 px-3 ${tone === id ? 'bg-brand-primary-50 text-brand-primary-700' : 'text-text-secondary'}`}
                >
                  {t(`reminders.tones.${id}`)}
                </button>
              ))}
            </div>
            <Button
              type="button"
              disabled={selected.size === 0 || prepare.isPending}
              onClick={() => prepare.mutate()}
              icon={<BellRing size={16} aria-hidden="true" />}
            >
              {t('reminders.prepare', { count: selected.size })}
            </Button>
            <span className="type-small text-text-secondary">{t('reminders.hint')}</span>
          </div>
          {prepare.isError ? <Banner kind="warning" message={t('reminders.errors.money_unavailable')} /> : null}
          <div className="overflow-x-auto">
            <table
              className="type-small w-full min-w-[720px] text-left text-text-primary"
              data-testid="reminders-table"
            >
              <thead>
                <tr className="text-text-secondary">
                  <th className="w-8 py-2" aria-label={t('reminders.select')} />
                  <th className="py-2 font-normal">{t('reminders.cols.customer')}</th>
                  <th className="py-2 text-right font-normal">{t('reminders.cols.sum')}</th>
                  <th className="py-2 text-right font-normal">{t('reminders.cols.count')}</th>
                  <th className="py-2 text-right font-normal">{t('reminders.cols.oldest')}</th>
                  <th className="py-2 font-normal">{t('reminders.cols.last')}</th>
                  <th className="py-2 font-normal">{t('reminders.cols.contact')}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((d) => (
                  <tr key={d.company.money_id} className="border-t border-border-default">
                    <td className="py-2">
                      <input
                        type="checkbox"
                        aria-label={t('reminders.selectOne', { name: d.company.name })}
                        checked={selected.has(d.company.money_id)}
                        onChange={() => toggle(d.company.money_id)}
                        disabled={!d.contact}
                      />
                    </td>
                    <td className="py-2">
                      <span className="type-label block">{d.company.name}</span>
                      <span className="text-text-secondary">{d.invoices.map((i) => i.number).join(', ')}</span>
                    </td>
                    <td className="py-2 text-right tabular-nums">{money(d.overdue_total)}</td>
                    <td className="py-2 text-right">{d.invoice_count}</td>
                    <td className="py-2 text-right">{t('reminders.days', { count: d.oldest_days })}</td>
                    <td className="py-2">{d.last_reminder_at ? day(d.last_reminder_at) : '–'}</td>
                    <td className="py-2">
                      {d.contact ?? (
                        <span className="inline-flex items-center gap-1 text-warning-700">
                          <CircleAlert size={14} aria-hidden="true" />
                          {t('reminders.noContact')}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}

function Results({ results, names }: { results: ReminderResult[]; names: Map<string, string> }) {
  const { t } = useTranslation();
  return (
    <section
      aria-label={t('reminders.results')}
      className="flex flex-col gap-2 rounded-lg border border-border-default p-3"
      data-testid="reminders-results"
    >
      <h2 className="type-label text-text-primary">{t('reminders.results')}</h2>
      <ul className="flex flex-col gap-1">
        {results.map((r) => (
          <li key={r.company_money_id} className="type-small flex items-center gap-2 text-text-primary">
            <span className="min-w-0 flex-1 truncate">{names.get(r.company_money_id) ?? r.company_money_id}</span>
            {r.draft_id ? (
              <Link
                to={`/compose/${r.draft_id}`}
                className="inline-flex items-center gap-1 text-brand-primary-700 hover:underline"
              >
                <FileText size={14} aria-hidden="true" />
                {t('reminders.openDraft')}
              </Link>
            ) : (
              <span className="text-warning-700">
                {t(`reminders.errors.${r.error ?? 'generic'}`, { number: r.number ?? '', defaultValue: r.error ?? '' })}
              </span>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function HistoryTab() {
  const { t } = useTranslation();
  const history = useQuery({ queryKey: reminderHistoryKey, queryFn: fetchReminderHistory, retry: false });
  const rows = history.data ?? [];
  if (history.isPending) return <div aria-busy="true" className="h-10 animate-pulse rounded-sm bg-bg-muted" />;
  if (rows.length === 0) return <p className="type-body text-text-secondary">{t('reminders.historyEmpty')}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="type-small w-full min-w-[640px] text-left text-text-primary" data-testid="reminders-history">
        <thead>
          <tr className="text-text-secondary">
            <th className="py-2 font-normal">{t('reminders.hist.at')}</th>
            <th className="py-2 font-normal">{t('reminders.cols.customer')}</th>
            <th className="py-2 font-normal">{t('reminders.hist.invoices')}</th>
            <th className="py-2 font-normal">{t('reminders.tone')}</th>
            <th className="py-2 font-normal">{t('reminders.hist.state')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.at}-${r.company_money_id}`} className="border-t border-border-default">
              <td className="py-2">{new Date(r.at).toLocaleString('sk-SK')}</td>
              <td className="py-2">{r.company_name ?? '–'}</td>
              <td className="py-2">{r.invoices.join(', ')}</td>
              <td className="py-2">{r.tone ? t(`reminders.tones.${r.tone}`) : '–'}</td>
              <td className="py-2">
                {t(`reminders.states.${r.draft_status ?? 'deleted'}`, { defaultValue: r.draft_status ?? '' })}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
