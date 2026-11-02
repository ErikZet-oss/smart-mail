import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { BellRing, CircleAlert, FileText, Search } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, Navigate } from 'react-router-dom';

import { Banner } from '../../components/Banner';
import { Button } from '../../components/Button';
import { AppShell } from '../../components/shell/AppShell';
import { MOBILE_QUERY, useMediaQuery } from '../../lib/useMediaQuery';
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
  type Debtor,
  type ReminderResult,
  type ReminderTone,
} from './moneyApi';
import { DocsHeader } from './DocsHeader';
import { DOCS_ROLES } from './docsAccess';

const ROLES = DOCS_ROLES;
const OVERDUE_MIN = [0, 14, 30, 60] as const;
const SUM_MIN = [0, 100, 1000] as const;

/**
 * W8b Upomienky in the Doklady hub (Phase 3e, Figma 57:47085): customers with overdue invoices → „Pripraviť
 * upomienky“ → one draft per customer in Koncepty (E2 table + Money PDFs) → the person checks and sends each.
 * No change of reminder dates in Money (MONEY_API §5.2). Only with FEATURE_MONEY; accounting, sales, admin.
 */
export function ScreenW8b() {
  const { t } = useTranslation();
  const features = useFeaturesState();
  const me = useQuery({ queryKey: ['me'], queryFn: fetchMe, retry: false });
  const [tab, setTab] = useState<'open' | 'history'>('open');
  const allowed = ROLES.has(me.data?.person?.role ?? '');
  const debtors = useQuery({
    queryKey: debtorsKey,
    queryFn: fetchDebtors,
    retry: false,
    enabled: features.money && allowed,
  });
  if (features.loaded && !features.money) return <Navigate to="/404" replace />;
  const count = debtors.data?.length;
  return (
    <AppShell section="documents">
      <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto bg-bg-canvas" data-testid="screen-w8b">
        <DocsHeader active="reminders" counts={{ reminders: count }} />
        <div className="flex flex-col gap-4 p-4 md:p-6">
          <div role="tablist" aria-label={t('reminders.title')} className="flex gap-2">
            {(['open', 'history'] as const).map((id) => (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={tab === id}
                onClick={() => setTab(id)}
                className={`type-label h-8 rounded-full border px-3 ${
                  tab === id
                    ? 'border-brand-primary-600 bg-brand-primary-50 text-brand-primary-700'
                    : 'border-border-default text-text-secondary hover:bg-bg-subtle'
                }`}
              >
                {id === 'open' && count != null ? t('reminders.tabs.openCount', { count }) : t(`reminders.tabs.${id}`)}
              </button>
            ))}
          </div>
          {!features.loaded || !me.data ? null : !allowed ? (
            <Banner kind="info" message={t('reminders.roleOnly')} />
          ) : tab === 'open' ? (
            <OpenTab debtors={debtors} />
          ) : (
            <HistoryTab />
          )}
        </div>
      </main>
    </AppShell>
  );
}

type DebtorsQuery = ReturnType<typeof useQuery<Debtor[]>>;

function lastReminder(d: Debtor, t: (key: string, o?: Record<string, unknown>) => string): string {
  if (!d.last_reminder_at) return '—';
  const tone = d.last_reminder_tone ? ` (${t(`reminders.tonesLower.${d.last_reminder_tone}`)})` : '';
  return `${day(d.last_reminder_at)}${tone}`;
}

function OpenTab({ debtors }: { debtors: DebtorsQuery }) {
  const { t } = useTranslation();
  const mobile = useMediaQuery(MOBILE_QUERY);
  const qc = useQueryClient();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [tone, setTone] = useState<ReminderTone>('polite');
  const [results, setResults] = useState<ReminderResult[] | null>(null);
  const [q, setQ] = useState('');
  const [overdueMin, setOverdueMin] = useState<number>(0);
  const [sumMin, setSumMin] = useState<number>(0);
  const [noReminder, setNoReminder] = useState(false);
  const prepare = useMutation({
    mutationFn: () => prepareReminders([...selected], tone),
    onSuccess: (out) => {
      setResults(out);
      setSelected(new Set());
      void qc.invalidateQueries({ queryKey: debtorsKey });
      void qc.invalidateQueries({ queryKey: reminderHistoryKey });
    },
  });
  const all = useMemo(() => debtors.data ?? [], [debtors.data]);
  const rows = useMemo(() => {
    const needle = q.trim().toLocaleLowerCase('sk');
    return all.filter(
      (d) =>
        (!needle ||
          d.company.name.toLocaleLowerCase('sk').includes(needle) ||
          (d.company.ico ?? '').includes(needle)) &&
        d.oldest_days > overdueMin &&
        Number(d.overdue_total) >= sumMin &&
        (!noReminder || !d.last_reminder_at),
    );
  }, [all, q, overdueMin, sumMin, noReminder]);
  const names = new Map(all.map((d) => [d.company.money_id, d.company.name]));
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
  if (all.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 py-16 text-center" data-testid="reminders-empty">
        <BellRing size={32} aria-hidden="true" className="text-text-tertiary" />
        <p className="type-heading text-text-primary">{t('reminders.emptyTitle')}</p>
        <p className="type-body text-text-secondary">{t('reminders.emptyText')}</p>
      </div>
    );
  }
  return (
    <>
      {results ? <Results results={results} names={names} /> : null}
      <div className="flex flex-wrap items-center gap-2" data-testid="reminders-filters">
        <label className="relative">
          <span className="sr-only">{t('reminders.filters.search')}</span>
          <Search
            size={16}
            aria-hidden="true"
            className="pointer-events-none absolute top-1/2 left-2 -translate-y-1/2 text-text-tertiary"
          />
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t('reminders.filters.search')}
            className="type-body h-9 w-56 rounded-sm border border-border-default bg-bg-canvas pr-2 pl-8"
          />
        </label>
        <select
          aria-label={t('reminders.filters.overdueLabel')}
          value={overdueMin}
          onChange={(e) => setOverdueMin(Number(e.target.value))}
          className="type-body h-9 rounded-sm border border-border-default bg-bg-canvas px-2"
        >
          {OVERDUE_MIN.map((n) => (
            <option key={n} value={n}>
              {t('reminders.filters.overdue', { count: n })}
            </option>
          ))}
        </select>
        <select
          aria-label={t('reminders.filters.sumLabel')}
          value={sumMin}
          onChange={(e) => setSumMin(Number(e.target.value))}
          className="type-body h-9 rounded-sm border border-border-default bg-bg-canvas px-2"
        >
          {SUM_MIN.map((n) => (
            <option key={n} value={n}>
              {n === 0 ? t('reminders.filters.sumAll') : t('reminders.filters.sumOver', { sum: money(String(n)) })}
            </option>
          ))}
        </select>
        <button
          type="button"
          aria-pressed={noReminder}
          onClick={() => setNoReminder((v) => !v)}
          className={`type-small h-8 rounded-full border px-3 ${
            noReminder
              ? 'border-brand-primary-600 bg-brand-primary-50 text-brand-primary-700'
              : 'border-border-default text-text-secondary hover:bg-bg-subtle'
          }`}
        >
          {t('reminders.filters.noReminder')}
        </button>
        <div className="flex-1" />
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
      </div>
      <p className="type-small text-text-secondary">{t('reminders.hint')}</p>
      {prepare.isError ? <Banner kind="warning" message={t('reminders.errors.money_unavailable')} /> : null}
      {mobile ? (
        // #193 / Figma M13 `85:3245`: one card per customer instead of the wide table at 360 px
        <ul className="flex flex-col gap-2" data-testid="reminders-table">
          {rows.length === 0 ? (
            <li className="type-small px-3 py-6 text-center text-text-secondary">{t('reminders.filters.none')}</li>
          ) : null}
          {rows.map((d) => {
            const on = selected.has(d.company.money_id);
            return (
              <li
                key={d.company.money_id}
                className={`type-small flex gap-3 rounded-md border border-border-default p-3 text-text-primary ${
                  on ? 'bg-brand-primary-50' : 'bg-bg-canvas'
                }`}
              >
                <input
                  type="checkbox"
                  className="mt-1 shrink-0"
                  aria-label={t('reminders.selectOne', { name: d.company.name })}
                  checked={on}
                  onChange={() => toggle(d.company.money_id)}
                  disabled={!d.contact}
                />
                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <div className="flex items-start gap-2">
                    <Link
                      to={`/contacts/company/${d.company.money_id}?tab=documents`}
                      className="type-label min-w-0 flex-1 break-words text-text-primary hover:underline"
                    >
                      {d.company.name}
                    </Link>
                    <span className="shrink-0 font-medium text-danger-600 tabular-nums">{money(d.overdue_total)}</span>
                  </div>
                  <span className="break-words text-text-secondary">{d.invoices.map((i) => i.number).join(', ')}</span>
                  <span className="text-text-secondary">
                    {t('reminders.cols.count')}: {d.invoice_count} · {t('reminders.days', { count: d.oldest_days })}
                    {' · '}
                    {t('reminders.cols.last')}: {lastReminder(d, t)}
                  </span>
                  {d.contact ? (
                    <span className="break-all text-text-secondary">
                      {[d.contact_name, d.contact].filter(Boolean).join(' · ')}
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-warning-700">
                      <CircleAlert size={14} aria-hidden="true" />
                      {t('reminders.noContact')}
                    </span>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      ) : (
        <div className="overflow-x-auto rounded-md border border-border-default">
          <table className="type-small w-full min-w-[760px] text-left text-text-primary" data-testid="reminders-table">
            <thead className="bg-bg-subtle">
              <tr className="text-text-secondary">
                <th className="w-10 px-3 py-2" aria-label={t('reminders.select')} />
                <th className="px-2 py-2 font-normal">{t('reminders.cols.customer')}</th>
                <th className="px-2 py-2 text-right font-normal">{t('reminders.cols.sum')}</th>
                <th className="px-2 py-2 text-right font-normal">{t('reminders.cols.count')}</th>
                <th className="px-2 py-2 text-right font-normal">{t('reminders.cols.oldest')}</th>
                <th className="px-2 py-2 font-normal">{t('reminders.cols.last')}</th>
                <th className="px-2 py-2 font-normal">{t('reminders.cols.contact')}</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-3 py-6 text-center text-text-secondary">
                    {t('reminders.filters.none')}
                  </td>
                </tr>
              ) : null}
              {rows.map((d) => {
                const on = selected.has(d.company.money_id);
                return (
                  <tr
                    key={d.company.money_id}
                    className={`border-t border-border-default ${on ? 'bg-brand-primary-50' : ''}`}
                  >
                    <td className="px-3 py-2">
                      <input
                        type="checkbox"
                        aria-label={t('reminders.selectOne', { name: d.company.name })}
                        checked={on}
                        onChange={() => toggle(d.company.money_id)}
                        disabled={!d.contact}
                      />
                    </td>
                    <td className="px-2 py-2">
                      <Link
                        to={`/contacts/company/${d.company.money_id}?tab=documents`}
                        className="type-label block text-text-primary hover:underline"
                      >
                        {d.company.name}
                      </Link>
                      <span className="text-text-secondary">{d.invoices.map((i) => i.number).join(', ')}</span>
                    </td>
                    <td className="px-2 py-2 text-right font-medium text-danger-600 tabular-nums">
                      {money(d.overdue_total)}
                    </td>
                    <td className="px-2 py-2 text-right">{d.invoice_count}</td>
                    <td className="px-2 py-2 text-right">{t('reminders.days', { count: d.oldest_days })}</td>
                    <td className="px-2 py-2">{lastReminder(d, t)}</td>
                    <td className="px-2 py-2">
                      {d.contact ? (
                        [d.contact_name, d.contact].filter(Boolean).join(' · ')
                      ) : (
                        <span className="inline-flex items-center gap-1 text-warning-700">
                          <CircleAlert size={14} aria-hidden="true" />
                          {t('reminders.noContact')}
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
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
    <div className="overflow-x-auto rounded-md border border-border-default">
      <table className="type-small w-full min-w-[640px] text-left text-text-primary" data-testid="reminders-history">
        <thead className="bg-bg-subtle">
          <tr className="text-text-secondary">
            <th className="px-3 py-2 font-normal">{t('reminders.hist.at')}</th>
            <th className="px-2 py-2 font-normal">{t('reminders.cols.customer')}</th>
            <th className="px-2 py-2 font-normal">{t('reminders.hist.invoices')}</th>
            <th className="px-2 py-2 font-normal">{t('reminders.tone')}</th>
            <th className="px-2 py-2 font-normal">{t('reminders.hist.state')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.at}-${r.company_money_id}`} className="border-t border-border-default">
              <td className="px-3 py-2">{new Date(r.at).toLocaleString('sk-SK')}</td>
              <td className="px-2 py-2">{r.company_name ?? '–'}</td>
              <td className="px-2 py-2">{r.invoices.join(', ')}</td>
              <td className="px-2 py-2">{r.tone ? t(`reminders.tones.${r.tone}`) : '–'}</td>
              <td className="px-2 py-2">
                {t(`reminders.states.${r.draft_status ?? 'deleted'}`, { defaultValue: r.draft_status ?? '' })}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
