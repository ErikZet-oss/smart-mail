import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CircleAlert, CircleCheck, Database, RefreshCw } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Banner } from '../../components/Banner';
import { Button } from '../../components/Button';
import { useToasts } from '../../components/toastContext';
import { ApiError } from '../../lib/api';
import { INPUT } from './adminUi';
import {
  branchMoneyKey,
  fetchBranchMoney,
  saveBranchMoney,
  testBranchReport,
  type BranchMoney,
  type BranchMoneyList,
  fetchMoneyActivities,
  fetchMoneyReports,
  fetchMoneyWrites,
  fetchMoneyStatus,
  fetchMoneySync,
  moneyActivitiesKey,
  moneyReportsKey,
  moneyWritesKey,
  moneyStatusKey,
  moneySyncKey,
  saveMoneyInterval,
  saveMoneyActivities,
  saveMoneyReports,
  saveMoneyWrites,
  retryMoneyActivity,
  startMoneySync,
  testMoneyReport,
  type MoneyActivities,
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
      <h2 className="type-label text-text-secondary">{t('money.connection.stateTitle')}</h2>
      <section
        aria-label={t('money.connection.card')}
        className="flex flex-wrap items-start gap-3 rounded-lg border border-border-default bg-bg-canvas p-4"
      >
        <Database size={22} aria-hidden="true" className="mt-0.5 shrink-0 text-text-secondary" />
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            {s?.reachable ? (
              <CircleCheck size={16} aria-hidden="true" className="text-success-700" />
            ) : (
              <CircleAlert size={16} aria-hidden="true" className="text-warning-700" />
            )}
            <span className="type-label text-text-primary" data-testid="money-reachable">
              {status.isPending
                ? t('money.connection.checking')
                : s?.reachable
                  ? t('money.connection.ok')
                  : t('money.connection.down')}
            </span>
            {s?.agenda ? (
              <span
                data-testid="money-agenda"
                className={`type-small inline-flex h-6 items-center rounded-full border px-2 ${
                  s.agenda === 'TEST'
                    ? 'border-warning-600 bg-warning-50 text-warning-700'
                    : 'border-danger-600 bg-danger-50 text-danger-600'
                }`}
              >
                {t(`money.connection.agendaChip.${s.agenda}`, { defaultValue: s.agenda })}
                {s.backend === 'mock' ? ` · ${t('money.connection.mock')}` : ''}
              </span>
            ) : null}
          </div>
          <p className="type-small text-text-secondary" data-testid="money-state-line">
            {[
              s?.money_version ? t('money.connection.apiLine', { version: s.money_version }) : null,
              s?.latency_ms != null ? t('money.connection.latencyLine', { ms: s.latency_ms }) : null,
              t('money.connection.lastSyncLine', {
                when: when(s?.entities.find((e) => e.entity === 'companies')?.last_run_at ?? null, t),
              }),
            ]
              .filter(Boolean)
              .join(' · ')}
          </p>
          <p className="type-caption text-text-secondary">
            {t('money.connection.bridgeVersion')} {s?.bridge_version ?? '–'} ·{' '}
            {s?.writes_enabled ? t('money.connection.bridgeWritesOn') : t('money.connection.bridgeWritesOff')}
          </p>
        </div>
        <Button
          type="button"
          variant="secondary"
          disabled={status.isFetching}
          onClick={() => void status.refetch()}
          icon={<RefreshCw size={16} aria-hidden="true" className={status.isFetching ? 'animate-spin' : ''} />}
        >
          {t('money.connection.test')}
        </Button>
      </section>
      <WritesSwitch />
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
        {data?.running ? (
          <div className="flex min-w-[200px] flex-1 flex-col gap-1" data-testid="money-sync-progress">
            <span className="type-small text-text-secondary">{t('money.sync.running')}</span>
            <div
              role="progressbar"
              aria-label={t('money.sync.running')}
              className="h-1.5 overflow-hidden rounded-full bg-bg-muted"
            >
              <div className="h-full w-1/3 animate-pulse rounded-full bg-brand-primary-600" />
            </div>
          </div>
        ) : null}
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
              <td className="py-1">
                {r.error ? (
                  <span
                    title={t(`money.errors.${r.error}`, { defaultValue: r.error })}
                    className="type-caption inline-flex h-6 items-center rounded-full border border-danger-600 bg-danger-50 px-2 text-danger-600"
                  >
                    {r.error}
                  </span>
                ) : (
                  '–'
                )}
              </td>
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
      <p className="type-small text-text-secondary">{t('money.reports.branchInfo')}</p>
    </div>
  );
}

/** W12-11e Money (pobočka), #174: centre of the branch (Money codebook, never typed) and its own print reports, SK
 * only. Price list, warehouse, series and the template delivery note come with Phase 4. */
export function BranchMoneyPanel({ branchId }: { branchId: string }) {
  const { t } = useTranslation();
  const query = useQuery({ queryKey: branchMoneyKey, queryFn: fetchBranchMoney });
  if (query.isError) return <Banner kind="danger" message={t('money.errors.money_unavailable')} />;
  const branch = query.data?.branches.find((b) => b.id === branchId);
  if (!query.data || !branch) return null;
  return <BranchMoneyForm key={`${branchId}-${query.dataUpdatedAt}`} branch={branch} centres={query.data.centres} />;
}

function BranchMoneyForm({ branch, centres }: { branch: BranchMoney; centres: BranchMoneyList['centres'] }) {
  const { t } = useTranslation();
  const toasts = useToasts();
  const qc = useQueryClient();
  const [centre, setCentre] = useState(branch.centre_id ?? '');
  const [reports, setReports] = useState(branch.reports);
  const [number, setNumber] = useState('');
  const invalid = REPORT_KINDS.some((k) => reports[k] && !REPORT_ID.test(reports[k]));
  const fail = (e: unknown) => {
    const code = e instanceof ApiError ? e.detail.code : 'generic';
    toasts.error(t(`money.errors.${code}`, { defaultValue: t('mail.errors.generic') }));
  };
  const save = useMutation({
    mutationFn: () => saveBranchMoney(branch.id, { centre_id: centre || null, reports }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: branchMoneyKey });
      toasts.success(t('settings.saved'));
    },
    onError: fail,
  });
  const tryPdf = useMutation({
    mutationFn: (kind: string) => testBranchReport(branch.id, kind, number.trim()),
    onSuccess: (blob) => {
      const url = URL.createObjectURL(blob);
      window.open(url, '_blank', 'noopener');
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    },
    onError: fail,
  });
  return (
    <div className="flex max-w-[var(--layout-settings-form-max)] flex-col gap-4" data-testid="settings-branch-money">
      <label className="flex flex-col gap-1">
        <span className="type-label text-text-primary">{t('money.branch.centre')}</span>
        <select
          value={centre}
          onChange={(e) => setCentre(e.target.value)}
          className={INPUT}
          aria-invalid={branch.centre_missing}
        >
          <option value="">{t('money.branch.centreNone')}</option>
          {branch.centre_missing && branch.centre_id ? (
            <option value={branch.centre_id}>{t('money.branch.centreMissing')}</option>
          ) : null}
          {centres.map((c) => (
            <option key={c.id} value={c.id}>
              {[c.code, c.name].filter(Boolean).join(' – ')}
            </option>
          ))}
        </select>
        <span className="type-small text-text-secondary">{t('money.branch.centreHelp')}</span>
        {branch.centre_missing ? (
          <span className="type-small text-danger-600">{t('money.branch.centreMissing')}</span>
        ) : null}
      </label>
      {REPORT_KINDS.map((k) => {
        const bad = Boolean(reports[k]) && !REPORT_ID.test(reports[k]);
        return (
          <label key={k} className="flex flex-col gap-1">
            <span className="type-label text-text-primary">{t(`money.branch.report.${k}`)}</span>
            <input
              value={reports[k]}
              aria-invalid={bad}
              onChange={(e) => setReports({ ...reports, [k]: e.target.value.trim() })}
              placeholder={t('money.reports.placeholder')}
              className={`${INPUT} ${bad ? 'border-danger-600' : ''}`}
            />
            <span className="type-small text-text-secondary">{t('money.branch.reportHelp')}</span>
          </label>
        );
      })}
      {invalid ? <p className="type-small text-danger-600">{t('money.reports.invalid')}</p> : null}
      <div>
        <Button type="button" disabled={invalid || save.isPending} onClick={() => save.mutate()}>
          {t('settings.save')}
        </Button>
      </div>
      <section className="flex flex-col gap-2 rounded-lg border border-border-default p-3">
        <h3 className="type-label text-text-primary">{t('money.reports.tryTitle')}</h3>
        <label className="flex flex-col gap-1">
          <span className="type-small text-text-secondary">{t('money.branch.tryNumber')}</span>
          <input value={number} onChange={(e) => setNumber(e.target.value)} className={INPUT} />
        </label>
        <div className="flex flex-wrap gap-2">
          {REPORT_KINDS.map((k) => (
            <Button
              key={k}
              type="button"
              variant="secondary"
              disabled={number.trim().length < 3 || !branch.reports[k] || tryPdf.isPending}
              onClick={() => tryPdf.mutate(k)}
            >
              {t('money.reports.try', { kind: t(`money.reports.short.${k}`), lang: 'SK' })}
            </Button>
          ))}
        </div>
      </section>
      <p className="type-small text-text-secondary">{t('money.branch.later')}</p>
    </div>
  );
}

/** 13a „Zápisy do Money povolené“ ⚠ — the main switch of every Money write (Phase 3f), re-auth on change. */
function WritesSwitch() {
  const { t } = useTranslation();
  const toasts = useToasts();
  const qc = useQueryClient();
  const writes = useQuery({ queryKey: moneyWritesKey, queryFn: fetchMoneyWrites });
  const save = useMutation({
    mutationFn: (enabled: boolean) => saveMoneyWrites(enabled),
    onSuccess: (out) => {
      qc.setQueryData(moneyWritesKey, out);
      toasts.success(t('settings.saved'));
    },
    onError: (e) => {
      const code = e instanceof ApiError ? e.detail.code : 'generic';
      if (code !== 'reauth_required')
        toasts.error(t(`money.errors.${code}`, { defaultValue: t('mail.errors.generic') }));
    },
  });
  const on = writes.data?.enabled ?? false;
  return (
    <section className="flex flex-col gap-2 rounded-lg border border-border-default p-4" data-testid="money-writes">
      <h2 className="type-label text-text-secondary">{t('money.writes.title')}</h2>
      <label className="flex items-center gap-3">
        <input
          type="checkbox"
          role="switch"
          aria-checked={on}
          checked={on}
          disabled={!writes.data || save.isPending || (!on && !writes.data.key_configured)}
          onChange={(e) => save.mutate(e.target.checked)}
        />
        <span className="type-label text-text-primary">{t('money.writes.label')} ⚠</span>
      </label>
      <p className="type-small text-text-secondary">{t('money.writes.help')}</p>
      {writes.data && !writes.data.key_configured ? (
        <p className="type-small text-warning-700">{t('money.writes.noKey')}</p>
      ) : null}
    </section>
  );
}

/** W12-13d Aktivity (Phase 3f): switch, activity types from Money's codebook, writes that failed (manual retry). */
export function MoneyActivitiesPanel() {
  const query = useQuery({ queryKey: moneyActivitiesKey, queryFn: fetchMoneyActivities });
  if (!query.data) return null;
  // the form keeps unsaved choices when the list refreshes (e.g. after „Skúsiť znova“)
  return <ActivitiesForm initial={query.data} data={query.data} />;
}

function ActivitiesForm({ initial, data }: { initial: MoneyActivities; data: MoneyActivities }) {
  const { t } = useTranslation();
  const toasts = useToasts();
  const qc = useQueryClient();
  const [form, setForm] = useState({
    enabled: initial.enabled,
    type_email: initial.type_email,
    type_reminder: initial.type_reminder,
  });
  const error = (e: unknown) => {
    const code = e instanceof ApiError ? e.detail.code : 'generic';
    toasts.error(t(`money.errors.${code}`, { defaultValue: t('mail.errors.generic') }));
  };
  const save = useMutation({
    mutationFn: () => saveMoneyActivities(form),
    onSuccess: (out) => {
      qc.setQueryData(moneyActivitiesKey, out);
      toasts.success(t('settings.saved'));
    },
    onError: error,
  });
  const retry = useMutation({
    mutationFn: (draftId: string) => retryMoneyActivity(draftId),
    onSuccess: () => {
      toasts.success(t('money.activities.retried'));
      void qc.invalidateQueries({ queryKey: moneyActivitiesKey });
    },
    onError: error,
  });
  const missingType = form.enabled && !(form.type_email && form.type_reminder);
  const select = (key: 'type_email' | 'type_reminder') => (
    <label className="flex flex-col gap-1">
      <span className="type-label text-text-secondary">{t(`money.activities.${key}`)}</span>
      <select
        className={INPUT}
        value={form[key] ?? ''}
        onChange={(e) => setForm({ ...form, [key]: e.target.value || null })}
      >
        <option value="">{t('money.activities.choose')}</option>
        {initial.types.map((type) => (
          <option key={type.id} value={type.id}>
            {[type.code, type.name].filter(Boolean).join(' – ')}
          </option>
        ))}
      </select>
    </label>
  );
  return (
    <div
      className="flex max-w-[var(--layout-settings-form-max)] flex-col gap-4"
      data-testid="settings-money-activities"
    >
      {!data.writes_enabled ? <Banner kind="info" message={t('money.activities.writesOff')} /> : null}
      <label className="flex items-center gap-3">
        <input
          type="checkbox"
          role="switch"
          aria-checked={form.enabled}
          checked={form.enabled}
          onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
        />
        <span className="type-label text-text-primary">{t('money.activities.enabled')}</span>
      </label>
      <p className="type-small text-text-secondary">{t('money.activities.help')}</p>
      {initial.types.length === 0 ? (
        <p className="type-small text-warning-700">{t('money.activities.noTypes')}</p>
      ) : null}
      {select('type_email')}
      {select('type_reminder')}
      {missingType ? <p className="type-small text-danger-600">{t('money.activities.typeRequired')}</p> : null}
      <div>
        <Button type="button" disabled={missingType || save.isPending} onClick={() => save.mutate()}>
          {t('settings.save')}
        </Button>
      </div>
      <section className="flex flex-col gap-2" data-testid="money-activities-failed">
        <h3 className="type-label text-text-primary">{t('money.activities.failedTitle')}</h3>
        {data.failed.length === 0 ? (
          <p className="type-small text-text-secondary">{t('money.activities.failedEmpty')}</p>
        ) : (
          <ul className="flex flex-col divide-y divide-border-default rounded-md border border-border-default">
            {data.failed.map((f) => (
              <li key={f.draft_id} className="type-small flex items-center gap-2 px-3 py-2 text-text-primary">
                <span className="min-w-0 flex-1">
                  <span className="block">
                    {new Date(f.at).toLocaleString('sk-SK')} · {f.invoices.join(', ') || '–'}
                  </span>
                  <span className="block text-warning-700">
                    {t(`money.errors.${f.error ?? 'generic'}`, { defaultValue: f.error ?? '' })}
                  </span>
                </span>
                <Button
                  type="button"
                  variant="secondary"
                  disabled={!data.writes_enabled || retry.isPending}
                  onClick={() => retry.mutate(f.draft_id)}
                >
                  {t('money.activities.retry')}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
