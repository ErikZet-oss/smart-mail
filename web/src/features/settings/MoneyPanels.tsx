import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CircleAlert, CircleCheck, RefreshCw } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Banner } from '../../components/Banner';
import { Button } from '../../components/Button';
import { useToasts } from '../../components/toastContext';
import { ApiError } from '../../lib/api';
import { INPUT } from './adminUi';
import {
  fetchMoneyReports,
  fetchMoneyStatus,
  fetchMoneySync,
  moneyReportsKey,
  moneyStatusKey,
  moneySyncKey,
  saveMoneyInterval,
  saveMoneyReports,
  startMoneySync,
  testMoneyReport,
  type MoneyReports,
  type MoneyEntityState,
} from './settingsApi';

const INTERVALS = [5, 15, 30, 60] as const;

function when(value: string | null, t: (k: string) => string) {
  return value ? new Date(value).toLocaleString('sk-SK') : t('money.never');
}

/** W12-13a Prepojenie (Phase 3b): status card of the Money bridge; „Otestovať“ asks again. Read-only in Phase 3. */
export function MoneyConnectionPanel() {
  const { t } = useTranslation();
  const status = useQuery({ queryKey: moneyStatusKey, queryFn: fetchMoneyStatus });
  const s = status.data;
  return (
    <div
      className="flex max-w-[var(--layout-settings-form-max)] flex-col gap-4"
      data-testid="settings-money-connection"
    >
      {s && !s.reachable ? (
        <Banner
          kind="warning"
          message={t('money.connection.unavailable')}
          details={[t(`money.errors.${s.error ?? 'money_unavailable'}`, { defaultValue: s.error ?? '' })]}
        />
      ) : null}
      <section
        aria-label={t('money.connection.card')}
        className="flex flex-col gap-3 rounded-lg border border-border-default bg-bg-canvas p-4"
      >
        <div className="flex items-center gap-2">
          {s?.reachable ? (
            <CircleCheck size={18} aria-hidden="true" className="text-success-700" />
          ) : (
            <CircleAlert size={18} aria-hidden="true" className="text-warning-700" />
          )}
          <span className="type-label text-text-primary" data-testid="money-reachable">
            {status.isPending
              ? t('money.connection.checking')
              : s?.reachable
                ? t('money.connection.ok')
                : t('money.connection.down')}
          </span>
        </div>
        <dl className="type-small grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-text-primary">
          <dt className="text-text-secondary">{t('money.connection.agenda')}</dt>
          <dd data-testid="money-agenda">
            {s?.agenda ? t(`money.connection.agendas.${s.agenda}`, { defaultValue: s.agenda }) : '–'}
            {s?.backend === 'mock' ? ` · ${t('money.connection.mock')}` : ''}
          </dd>
          <dt className="text-text-secondary">{t('money.connection.apiVersion')}</dt>
          <dd>{s?.money_version ?? '–'}</dd>
          <dt className="text-text-secondary">{t('money.connection.bridgeVersion')}</dt>
          <dd>{s?.bridge_version ?? '–'}</dd>
          <dt className="text-text-secondary">{t('money.connection.latency')}</dt>
          <dd>{s?.latency_ms != null ? `${s.latency_ms} ms` : '–'}</dd>
          <dt className="text-text-secondary">{t('money.connection.lastSync')}</dt>
          <dd>{when(s?.entities.find((e) => e.entity === 'companies')?.last_run_at ?? null, t)}</dd>
          <dt className="text-text-secondary">{t('money.connection.writes')}</dt>
          <dd>{t('money.connection.writesOff')}</dd>
        </dl>
        <div>
          <Button
            type="button"
            variant="secondary"
            disabled={status.isFetching}
            onClick={() => void status.refetch()}
            icon={<RefreshCw size={16} aria-hidden="true" />}
          >
            {t('money.connection.test')}
          </Button>
        </div>
      </section>
      {s ? <CacheTable entities={s.entities} /> : null}
    </div>
  );
}

function CacheTable({ entities }: { entities: MoneyEntityState[] }) {
  const { t } = useTranslation();
  return (
    <table className="type-small w-full text-left text-text-primary">
      <caption className="type-label mb-1 text-left text-text-secondary">{t('money.cache.title')}</caption>
      <thead>
        <tr className="text-text-secondary">
          <th className="py-1 font-normal">{t('money.cache.entity')}</th>
          <th className="py-1 font-normal">{t('money.cache.rows')}</th>
          <th className="py-1 font-normal">{t('money.cache.lastRun')}</th>
          <th className="py-1 font-normal">{t('money.cache.status')}</th>
        </tr>
      </thead>
      <tbody>
        {entities.map((e) => (
          <tr key={e.entity} className="border-t border-border-default">
            <td className="py-1">{t(`money.entities.${e.entity}`)}</td>
            <td className="py-1">{e.rows}</td>
            <td className="py-1">{when(e.last_run_at, t)}</td>
            <td className="py-1">
              {e.status === 'error'
                ? t(`money.errors.${e.error ?? 'money_unavailable'}`, { defaultValue: e.error ?? '' })
                : e.status
                  ? t('money.cache.ok')
                  : '–'}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** W12-13e Synchronizácia (Phase 3b): interval, „Synchronizovať teraz“, last 20 runs. */
export function MoneySyncPanel() {
  const { t } = useTranslation();
  const toasts = useToasts();
  const qc = useQueryClient();
  const sync = useQuery({
    queryKey: moneySyncKey,
    queryFn: fetchMoneySync,
    refetchInterval: (q) => (q.state.data?.running ? 3000 : false),
  });
  const error = (e: unknown) => {
    const code = e instanceof ApiError ? e.detail.code : 'generic';
    toasts.error(t(`money.errors.${code}`, { defaultValue: t('mail.errors.generic') }));
  };
  const interval = useMutation({
    mutationFn: (minutes: number) => saveMoneyInterval(minutes),
    onSuccess: (out) => {
      qc.setQueryData(moneySyncKey, out);
      toasts.success(t('settings.saved'));
    },
    onError: error,
  });
  const now = useMutation({
    mutationFn: startMoneySync,
    onSuccess: () => {
      toasts.success(t('money.sync.started'));
      void qc.invalidateQueries({ queryKey: moneySyncKey });
    },
    onError: error,
  });
  const data = sync.data;
  return (
    <div className="flex max-w-[var(--layout-settings-form-max)] flex-col gap-4" data-testid="settings-money-sync">
      <label className="flex flex-col gap-1">
        <span className="type-label text-text-secondary">{t('money.sync.interval')}</span>
        <select
          className={INPUT}
          value={data?.interval_min ?? 15}
          disabled={!data || interval.isPending}
          onChange={(e) => interval.mutate(Number(e.target.value))}
        >
          {INTERVALS.map((m) => (
            <option key={m} value={m}>
              {t('money.sync.minutes', { count: m })}
            </option>
          ))}
        </select>
        <span className="type-small text-text-secondary">{t('money.sync.intervalHelp')}</span>
      </label>
      <div className="flex items-center gap-3">
        <Button
          type="button"
          disabled={!data || data.running || now.isPending}
          onClick={() => now.mutate()}
          icon={<RefreshCw size={16} aria-hidden="true" className={data?.running ? 'animate-spin' : ''} />}
        >
          {t('money.sync.now')}
        </Button>
        {data?.running ? <span className="type-small text-text-secondary">{t('money.sync.running')}</span> : null}
      </div>
      <table className="type-small w-full text-left text-text-primary" data-testid="money-sync-history">
        <caption className="type-label mb-1 text-left text-text-secondary">{t('money.sync.history')}</caption>
        <thead>
          <tr className="text-text-secondary">
            <th className="py-1 font-normal">{t('money.sync.at')}</th>
            <th className="py-1 font-normal">{t('money.cache.entity')}</th>
            <th className="py-1 font-normal">{t('money.sync.duration')}</th>
            <th className="py-1 font-normal">{t('money.sync.changed')}</th>
            <th className="py-1 font-normal">{t('money.sync.errors')}</th>
          </tr>
        </thead>
        <tbody>
          {data && data.history.length === 0 ? (
            <tr>
              <td colSpan={5} className="py-2 text-text-secondary">
                {t('money.sync.empty')}
              </td>
            </tr>
          ) : null}
          {data?.history.map((r) => (
            <tr key={`${r.entity}-${r.at}`} className="border-t border-border-default">
              <td className="py-1">{when(r.at, t)}</td>
              <td className="py-1">
                {t(`money.entities.${r.entity}`)}
                {r.full ? ` · ${t('money.sync.full')}` : ''}
              </td>
              <td className="py-1">{(r.duration_ms / 1000).toLocaleString('sk-SK', { maximumFractionDigits: 1 })} s</td>
              <td className="py-1">{r.changed}</td>
              <td className="py-1">{r.error ? t(`money.errors.${r.error}`, { defaultValue: r.error }) : '–'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const REPORT_KINDS = ['invoice', 'proforma'] as const;
const REPORT_LANGS = ['sk', 'en', 'de'] as const;
const REPORT_ID = /^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|\d{1,9})$/;

/** W12-13b Tlačové zostavy (Phase 3d): Money report id per document and language + „Vyskúšať PDF“. */
export function MoneyReportsPanel() {
  const query = useQuery({ queryKey: moneyReportsKey, queryFn: fetchMoneyReports });
  if (!query.data) return null;
  return <ReportsForm key={query.dataUpdatedAt} initial={query.data} />;
}

function ReportsForm({ initial }: { initial: MoneyReports }) {
  const { t } = useTranslation();
  const toasts = useToasts();
  const qc = useQueryClient();
  const [form, setForm] = useState<MoneyReports>(initial);
  const [number, setNumber] = useState('');
  const invalid = REPORT_KINDS.some((k) => REPORT_LANGS.some((l) => form[k][l] && !REPORT_ID.test(form[k][l])));
  const save = useMutation({
    mutationFn: () => saveMoneyReports(form),
    onSuccess: (out) => {
      qc.setQueryData(moneyReportsKey, out);
      toasts.success(t('settings.saved'));
    },
    onError: (e) => {
      const code = e instanceof ApiError ? e.detail.code : 'generic';
      toasts.error(t(`money.errors.${code}`, { defaultValue: t('mail.errors.generic') }));
    },
  });
  const tryPdf = useMutation({
    mutationFn: ({ kind, lang }: { kind: string; lang: string }) => testMoneyReport(kind, lang, number.trim()),
    onSuccess: (blob) => {
      const url = URL.createObjectURL(blob);
      window.open(url, '_blank', 'noopener');
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    },
    onError: (e) => {
      const code = e instanceof ApiError ? e.detail.code : 'generic';
      toasts.error(t(`money.errors.${code}`, { defaultValue: t('mail.errors.generic') }));
    },
  });
  return (
    <div className="flex max-w-[var(--layout-settings-form-max)] flex-col gap-4" data-testid="settings-money-reports">
      <table className="type-small w-full text-left text-text-primary">
        <thead>
          <tr className="text-text-secondary">
            <th className="py-1 font-normal">{t('money.reports.document')}</th>
            {REPORT_LANGS.map((l) => (
              <th key={l} className="py-1 font-normal">
                {l.toUpperCase()}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {REPORT_KINDS.map((k) => (
            <tr key={k} className="border-t border-border-default">
              <td className="py-2 pr-2">{t(`money.reports.kinds.${k}`)}</td>
              {REPORT_LANGS.map((l) => {
                const value = form[k][l];
                const bad = Boolean(value) && !REPORT_ID.test(value);
                return (
                  <td key={l} className="py-2 pr-2">
                    <input
                      aria-label={t('money.reports.field', {
                        kind: t(`money.reports.kinds.${k}`),
                        lang: l.toUpperCase(),
                      })}
                      aria-invalid={bad}
                      value={value}
                      onChange={(e) => setForm({ ...form, [k]: { ...form[k], [l]: e.target.value.trim() } })}
                      placeholder={l === 'sk' ? t('money.reports.placeholder') : t('money.reports.fallback')}
                      className={`${INPUT} w-full ${bad ? 'border-danger-600' : ''}`}
                    />
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {invalid ? <p className="type-small text-danger-600">{t('money.reports.invalid')}</p> : null}
      <div>
        <Button type="button" disabled={invalid || save.isPending} onClick={() => save.mutate()}>
          {t('settings.save')}
        </Button>
      </div>
      <section className="flex flex-col gap-2 rounded-lg border border-border-default p-3">
        <h3 className="type-label text-text-primary">{t('money.reports.tryTitle')}</h3>
        <label className="flex flex-col gap-1">
          <span className="type-small text-text-secondary">{t('money.reports.tryNumber')}</span>
          <input value={number} onChange={(e) => setNumber(e.target.value)} className={INPUT} />
        </label>
        <div className="flex flex-wrap gap-2">
          {REPORT_KINDS.flatMap((k) =>
            REPORT_LANGS.map((l) => (
              <Button
                key={`${k}-${l}`}
                type="button"
                variant="secondary"
                disabled={number.trim().length < 3 || tryPdf.isPending}
                onClick={() => tryPdf.mutate({ kind: k, lang: l })}
              >
                {t('money.reports.try', { kind: t(`money.reports.short.${k}`), lang: l.toUpperCase() })}
              </Button>
            )),
          )}
        </div>
      </section>
      <p className="type-small text-text-secondary">{t('money.reports.info')}</p>
    </div>
  );
}
