import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Lock } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { useToasts } from '../../components/toastContext';
import { adminErrorText } from './adminUi';
import {
  autonomyKey,
  autonomyOverviewKey,
  fetchAutonomy,
  fetchAutonomyOverview,
  saveAutonomy,
  type AutonomyAction,
} from './settingsApi';

const LEVELS = [0, 1, 2, 3, 4] as const;

/** W12-07 Samostatnosť (D8): each login sets its own levels; send and Money writes are locked at 2 (in code too). */
export function AutonomyMatrix({ disabled }: { disabled: boolean }) {
  const { t } = useTranslation();
  const toasts = useToasts();
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: autonomyKey, queryFn: fetchAutonomy });
  const save = useMutation({
    mutationFn: (levels: Record<string, number>) => saveAutonomy(levels),
    onSuccess: (out) => {
      queryClient.setQueryData(autonomyKey, out);
      toasts.success(t('settings.saved'));
    },
    onError: (error) => toasts.error(adminErrorText(t, error)),
  });
  const pick = (action: AutonomyAction, level: number) => {
    if (level !== action.level) save.mutate({ [action.id]: level });
  };

  return (
    <section className="flex flex-col gap-2" aria-labelledby="ai-autonomy-title" data-testid="ai-autonomy">
      <h3 id="ai-autonomy-title" className="type-title text-text-primary">
        {t('ai.autonomy.title')} ⚠
      </h3>
      <p className="type-small text-text-secondary">{t('ai.autonomy.help')}</p>
      <p className="type-small text-text-secondary">{t('ai.autonomy.scope')}</p>
      <div className="overflow-x-auto">
        <table className="type-small w-full border-collapse text-text-primary">
          <thead>
            <tr className="border-b border-border-default text-left">
              <th scope="col" className="py-1.5 pr-2 font-medium">
                {t('ai.autonomy.action')}
              </th>
              {LEVELS.map((level) => (
                <th key={level} scope="col" className="px-1 py-1.5 text-center font-medium">
                  {t(`ai.autonomy.levels.${level}`)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(query.data?.actions ?? []).map((action) => (
              <tr key={action.id} className="border-b border-border-default" data-testid={`autonomy-${action.id}`}>
                <th scope="row" className="py-1.5 pr-2 text-left font-normal">
                  <span className="inline-flex items-center gap-1">
                    {t(`ai.autonomy.actions.${action.id}`)}
                    {action.hard ? (
                      <Lock size={14} aria-label={t('ai.autonomy.locked')} className="text-text-secondary" />
                    ) : null}
                  </span>
                </th>
                {LEVELS.map((level) => (
                  <td key={level} className="px-1 py-1.5 text-center">
                    <input
                      type="radio"
                      name={`autonomy-${action.id}`}
                      aria-label={`${t(`ai.autonomy.actions.${action.id}`)}: ${t(`ai.autonomy.levels.${level}`)}`}
                      checked={action.level === level}
                      disabled={disabled || save.isPending || level > action.max}
                      onChange={() => pick(action, level)}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="type-small inline-flex items-center gap-1 text-text-secondary">
        <Lock size={14} aria-hidden="true" />
        {t('ai.autonomy.hardRule')}
      </p>
    </section>
  );
}

/** W12-17b Samostatnosť AI (admin, read-only): no admin maximum — each login sets its own levels in 07 (D8). */
export function AutonomyOverview() {
  const { t } = useTranslation();
  const own = useQuery({ queryKey: autonomyKey, queryFn: fetchAutonomy });
  const overview = useQuery({ queryKey: autonomyOverviewKey, queryFn: fetchAutonomyOverview });
  const actions = own.data?.actions ?? [];
  return (
    <div className="flex flex-col gap-3" data-testid="settings-ai-autonomy-overview">
      <h2 className="type-heading text-text-primary">{t('ai.autonomy.overviewTitle')}</h2>
      <p className="type-small text-text-secondary">{t('ai.autonomy.overviewHelp')}</p>
      <p className="type-small inline-flex items-center gap-1 text-text-primary">
        <Lock size={14} aria-hidden="true" />
        {t('ai.autonomy.hardRule')}
      </p>
      <div className="overflow-x-auto">
        <table className="type-small w-full border-collapse text-text-primary">
          <thead>
            <tr className="border-b border-border-default text-left">
              <th scope="col" className="py-1.5 pr-2 font-medium">
                {t('ai.autonomy.action')}
              </th>
              {(overview.data ?? []).map((row) => (
                <th key={row.account_id} scope="col" className="px-2 py-1.5 font-medium">
                  {row.email}
                  <span className="block font-normal text-text-secondary">
                    {row.customized ? t('ai.autonomy.customized') : t('ai.autonomy.defaults')}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {actions.map((action) => (
              <tr key={action.id} className="border-b border-border-default">
                <th scope="row" className="py-1.5 pr-2 text-left font-normal">
                  {t(`ai.autonomy.actions.${action.id}`)}
                </th>
                {(overview.data ?? []).map((row) => (
                  <td key={row.account_id} className="px-2 py-1.5">
                    {t(`ai.autonomy.levels.${row.levels[action.id] ?? action.default}`)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
