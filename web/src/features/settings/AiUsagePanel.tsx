import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Download } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { ConfirmDialog } from '../../components/Dialog';
import { Switch } from '../../components/Switch';
import { useToasts } from '../../components/toastContext';
import { adminErrorText } from './adminUi';
import { fetchShadow, fetchUsage, saveShadow, shadowKey, usageKey, type AiUsage } from './settingsApi';

/** W12-17f Tieňový režim, spotreba a presnosť (admin, Phase 2f): shadow switch + read-only numbers, CSV export. */
export function AiUsagePanel() {
  const { t } = useTranslation();
  const toasts = useToasts();
  const queryClient = useQueryClient();
  const shadow = useQuery({ queryKey: shadowKey, queryFn: fetchShadow });
  const usage = useQuery({ queryKey: usageKey, queryFn: fetchUsage });
  const [confirmOff, setConfirmOff] = useState(false);
  const save = useMutation({
    mutationFn: (replies: boolean) => saveShadow(replies),
    onSuccess: (out) => {
      queryClient.setQueryData(shadowKey, out);
      setConfirmOff(false);
    },
    onError: (error) => toasts.error(adminErrorText(t, error)),
  });

  const u = usage.data;
  const max = Math.max(0.0001, ...(u?.days ?? []).map((d) => Number(d.cost_usd)));
  const s = u?.suggestions;
  return (
    <div className="flex max-w-[var(--layout-settings-form-max)] flex-col gap-8" data-testid="settings-ai-usage">
      <section className="flex flex-col gap-2" aria-labelledby="ai-shadow-title">
        <h2 id="ai-shadow-title" className="type-heading text-text-primary">
          {t('ai.usage.shadowTitle')}
        </h2>
        <p className="type-small text-text-secondary">{t('ai.usage.shadowHelp')}</p>
        {shadow.data ? (
          <Switch
            checked={shadow.data.replies}
            disabled={save.isPending}
            onChange={(on) => (on ? save.mutate(true) : setConfirmOff(true))}
            label={t('ai.usage.shadowReplies')}
          />
        ) : null}
      </section>

      <section className="flex flex-col gap-2" aria-labelledby="ai-cost-title">
        <div className="flex items-center justify-between gap-2">
          <h2 id="ai-cost-title" className="type-heading text-text-primary">
            {t('ai.usage.costTitle')}
          </h2>
          <a
            href="/api/settings/ai/usage.csv"
            className="type-label inline-flex items-center gap-1 text-brand-primary-700 hover:underline"
          >
            <Download size={16} aria-hidden="true" />
            {t('ai.usage.csv')}
          </a>
        </div>
        {u ? (
          <>
            <p className="type-small text-text-primary">
              {t('ai.usage.total', { total: u.total_cost_usd, budget: u.budget_usd })}
            </p>
            {u.days.length === 0 ? (
              <p className="type-small text-text-secondary">{t('ai.usage.none')}</p>
            ) : (
              <ul className="flex h-24 items-end gap-1" aria-label={t('ai.usage.costTitle')}>
                {u.days.map((d) => (
                  <li
                    key={d.date}
                    className="min-w-[6px] flex-1 rounded-t-sm bg-brand-primary-600"
                    style={{ height: `${Math.max(4, (Number(d.cost_usd) / max) * 100)}%` }}
                    title={t('ai.usage.perDay', { date: d.date, cost: d.cost_usd, runs: d.runs })}
                    aria-label={t('ai.usage.perDay', { date: d.date, cost: d.cost_usd, runs: d.runs })}
                  />
                ))}
              </ul>
            )}
            <dl className="type-small grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-text-primary">
              {Object.entries(u.cost_by_purpose).map(([purpose, cost]) => (
                <div key={purpose} className="contents">
                  <dt className="text-text-secondary">
                    {t(`ai.usage.purposes.${purpose}`, { defaultValue: purpose })}
                  </dt>
                  <dd>{cost} USD</dd>
                </div>
              ))}
            </dl>
          </>
        ) : null}
      </section>

      {s && u ? (
        <section className="flex flex-col gap-2" aria-labelledby="ai-accuracy-title">
          <h2 id="ai-accuracy-title" className="type-heading text-text-primary">
            {t('ai.usage.accuracyTitle')}
          </h2>
          <dl className="type-small grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-text-primary">
            <dt className="text-text-secondary">{t('ai.usage.created')}</dt>
            <dd>
              {s.total} ({t('ai.usage.inShadow')} {s.shadow})
            </dd>
            <dt className="text-text-secondary">{t('ai.usage.approved')}</dt>
            <dd>{s.approved}</dd>
            <dt className="text-text-secondary">{t('ai.usage.unedited')}</dt>
            <dd>{s.approved_unedited_pct === null ? t('ai.usage.noDecisions') : `${s.approved_unedited_pct} %`}</dd>
            <dt className="text-text-secondary">{t('ai.usage.rejected')}</dt>
            <dd>{s.rejected}</dd>
          </dl>
          <h3 className="type-label mt-2 text-text-primary">{t('ai.usage.reasonsTitle')}</h3>
          <Counts values={u.reject_reasons} label={(k) => t(`ai.card.reasons.${k}`, { defaultValue: k })} />
          <h3 className="type-label mt-2 text-text-primary">{t('ai.usage.categoriesTitle')}</h3>
          <Counts values={u.categories} label={(k) => t(`ai.categories.${k}.label`, { defaultValue: k })} />
        </section>
      ) : null}

      {u ? <EvalSection evalRun={u.eval ?? null} /> : null}

      {confirmOff ? (
        <ConfirmDialog
          title={t('ai.usage.shadowOffTitle')}
          body={t('ai.usage.shadowOffBody')}
          confirmLabel={t('ai.usage.shadowOffConfirm')}
          busy={save.isPending}
          onConfirm={() => save.mutate(false)}
          onClose={() => setConfirmOff(false)}
        />
      ) : null}
    </div>
  );
}

function Counts({ values, label }: { values: Record<string, number>; label: (key: string) => string }) {
  const { t } = useTranslation();
  const entries = Object.entries(values);
  if (entries.length === 0) return <p className="type-small text-text-secondary">{t('ai.usage.none')}</p>;
  return (
    <ul className="type-small flex flex-col gap-0.5 text-text-primary">
      {entries.map(([key, n]) => (
        <li key={key} className="flex justify-between gap-4">
          <span>{label(key)}</span>
          <span>{n}</span>
        </li>
      ))}
    </ul>
  );
}

/** Presnosť kategórií — the last server eval (`make eval … --save`): accuracy vs the 90 % gate and the confusions. */
function EvalSection({ evalRun }: { evalRun: AiUsage['eval'] }) {
  const { t } = useTranslation();
  const cat = (k: string) =>
    k === '(none)' ? t('ai.usage.eval.none') : t(`ai.categories.${k}.label`, { defaultValue: k });
  return (
    <section className="flex flex-col gap-2" aria-labelledby="ai-eval-title" data-testid="ai-eval">
      <h2 id="ai-eval-title" className="type-heading text-text-primary">
        {t('ai.usage.eval.title')}
      </h2>
      {evalRun === null ? (
        <p className="type-small text-text-secondary">{t('ai.usage.eval.never')}</p>
      ) : (
        <>
          <p className="type-small text-text-primary">
            {t('ai.usage.eval.result', {
              accuracy: evalRun.accuracy ?? '–',
              gate: evalRun.gate,
              total: evalRun.total,
              date: new Date(evalRun.run_at).toLocaleDateString('sk-SK'),
            })}{' '}
            <strong>{evalRun.passed ? t('ai.usage.eval.passed') : t('ai.usage.eval.failed')}</strong>
          </p>
          {evalRun.too_small ? <p className="type-small text-text-secondary">{t('ai.usage.eval.tooSmall')}</p> : null}
          {evalRun.confusion.length === 0 ? (
            <p className="type-small text-text-secondary">{t('ai.usage.eval.noConfusion')}</p>
          ) : (
            <table className="type-small w-full border-collapse text-text-primary">
              <thead>
                <tr className="border-b border-border-default text-left">
                  <th scope="col" className="py-1 pr-2 font-medium">
                    {t('ai.usage.eval.label')}
                  </th>
                  <th scope="col" className="px-2 py-1 font-medium">
                    {t('ai.usage.eval.predicted')}
                  </th>
                  <th scope="col" className="py-1 pl-2 text-right font-medium">
                    {t('ai.usage.eval.count')}
                  </th>
                </tr>
              </thead>
              <tbody>
                {evalRun.confusion.map((c) => (
                  <tr key={`${c.label}>${c.predicted}`} className="border-b border-border-default">
                    <td className="py-1 pr-2">{cat(c.label)}</td>
                    <td className="px-2 py-1">{cat(c.predicted)}</td>
                    <td className="py-1 pl-2 text-right">{c.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </section>
  );
}
