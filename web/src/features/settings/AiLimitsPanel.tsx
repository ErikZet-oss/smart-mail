import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '../../components/Button';
import { useToasts } from '../../components/toastContext';
import { adminErrorText, INPUT } from './adminUi';
import { fetchLimits, limitsKey, saveLimits, type AiLimits, type AiLimitsIn } from './settingsApi';

/** W12-17a Poskytovateľ a rozpočet (admin, #116). Provider and models come from the server; ⚠ save needs re-auth. */
export function AiLimitsPanel() {
  const query = useQuery({ queryKey: limitsKey, queryFn: fetchLimits });
  if (!query.data) return null;
  return <LimitsForm key={query.dataUpdatedAt} limits={query.data} />;
}

function LimitsForm({ limits }: { limits: AiLimits }) {
  const { t } = useTranslation();
  const toasts = useToasts();
  const queryClient = useQueryClient();
  const [form, setForm] = useState<AiLimitsIn>({
    daily_budget_usd: limits.budget_source === 'app' ? limits.daily_budget_usd : null,
    alert_pct: limits.alert_pct,
    on_exhausted: limits.on_exhausted,
    retention_days: limits.retention_days,
  });
  const save = useMutation({
    mutationFn: () => saveLimits(form),
    onSuccess: (out) => {
      queryClient.setQueryData(limitsKey, out);
      toasts.success(t('settings.saved'));
    },
    onError: (error) => toasts.error(adminErrorText(t, error)),
  });

  return (
    <div className="flex max-w-[var(--layout-settings-form-max)] flex-col gap-4" data-testid="settings-ai-limits">
      <h2 className="type-heading text-text-primary">{t('ai.limits.title')}</h2>
      <dl className="type-small grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-text-primary">
        <dt className="text-text-secondary">{t('ai.limits.provider')}</dt>
        <dd>
          {t(`ai.limits.providers.${limits.provider}`)}
          {limits.region ? ` · ${limits.region}` : ''}
        </dd>
        {limits.models.map((m) => (
          <div key={m.purpose} className="contents">
            <dt className="text-text-secondary">{t(`ai.limits.purposes.${m.purpose}`)}</dt>
            <dd className="type-mono">{m.model ?? t('ai.limits.noModel')}</dd>
          </div>
        ))}
      </dl>
      <p className="type-small text-text-secondary">{t('ai.limits.serverHint')}</p>

      <label className="flex flex-col gap-1">
        <span className="type-label text-text-secondary">{t('ai.limits.budget')} ⚠</span>
        <input
          className={INPUT}
          inputMode="decimal"
          placeholder={limits.env_budget_usd}
          value={form.daily_budget_usd ?? ''}
          onChange={(e) => setForm({ ...form, daily_budget_usd: e.target.value.trim() ? e.target.value : null })}
        />
        <span className="type-small text-text-secondary" data-testid="budget-source">
          {limits.budget_source === 'app'
            ? t('ai.limits.sourceApp', { value: limits.daily_budget_usd })
            : t('ai.limits.sourceEnv', { value: limits.env_budget_usd })}
        </span>
      </label>
      <label className="flex flex-col gap-1">
        <span className="type-label text-text-secondary">{t('ai.limits.alert')}</span>
        <input
          className={INPUT}
          type="number"
          min={1}
          max={100}
          value={form.alert_pct}
          onChange={(e) => setForm({ ...form, alert_pct: Number(e.target.value) })}
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className="type-label text-text-secondary">{t('ai.limits.onExhausted')}</span>
        <select
          className={INPUT}
          value={form.on_exhausted}
          onChange={(e) => setForm({ ...form, on_exhausted: e.target.value as AiLimitsIn['on_exhausted'] })}
        >
          <option value="rules_only">{t('ai.limits.rulesOnly')}</option>
          <option value="ai_off">{t('ai.limits.aiOff')}</option>
        </select>
      </label>
      <label className="flex flex-col gap-1">
        <span className="type-label text-text-secondary">{t('ai.limits.retention')}</span>
        <select
          className={INPUT}
          value={form.retention_days}
          onChange={(e) => setForm({ ...form, retention_days: Number(e.target.value) as AiLimitsIn['retention_days'] })}
        >
          {[30, 90, 365].map((d) => (
            <option key={d} value={d}>
              {t('ai.limits.days', { count: d })}
            </option>
          ))}
        </select>
      </label>
      <Button
        type="button"
        className="self-start"
        icon={<Check size={16} aria-hidden="true" />}
        disabled={save.isPending}
        onClick={() => save.mutate()}
      >
        {t('settings.save')}
      </Button>
    </div>
  );
}
