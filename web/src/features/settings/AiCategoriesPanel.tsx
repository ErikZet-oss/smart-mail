import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, Plus, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '../../components/Button';
import { useToasts } from '../../components/toastContext';
import { adminErrorText, INPUT } from './adminUi';
import {
  categoriesKey,
  fetchCategories,
  saveCategories,
  type CategoryColor,
  type CategoryRow,
  type CategoryRowIn,
} from './settingsApi';

const MAX_CUSTOM = 15;
const COLORS: CategoryColor[] = ['warning', 'success', 'danger', 'info', 'brand', 'neutral'];

type Draft = CategoryRowIn & { key: string; builtin: boolean; locked: boolean; count: number; label: string | null };

const toDraft = (row: CategoryRow): Draft => ({
  key: row.id,
  id: row.id,
  label: row.label,
  description: row.description,
  color: row.color,
  enabled: row.enabled,
  builtin: row.builtin,
  locked: row.locked,
  count: row.count_30d,
});

/** W12-17c Kategórie (admin, #116): descriptions feed the classify prompt; switching off keeps stored mail. */
export function AiCategoriesPanel() {
  const query = useQuery({ queryKey: categoriesKey, queryFn: fetchCategories });
  if (!query.data) return null;
  return <CategoriesForm key={query.dataUpdatedAt} rows={query.data} />;
}

function CategoriesForm({ rows }: { rows: CategoryRow[] }) {
  const { t } = useTranslation();
  const toasts = useToasts();
  const queryClient = useQueryClient();
  const [drafts, setDrafts] = useState<Draft[]>(rows.map(toDraft));
  const customCount = drafts.filter((d) => !d.builtin).length;
  const update = (key: string, patch: Partial<Draft>) =>
    setDrafts((all) => all.map((d) => (d.key === key ? { ...d, ...patch } : d)));
  const save = useMutation({
    mutationFn: () =>
      saveCategories(
        drafts.map(({ id, label, description, color, enabled }) => ({ id, label, description, color, enabled })),
      ),
    onSuccess: (out) => {
      queryClient.setQueryData(categoriesKey, out);
      toasts.success(t('settings.saved'));
    },
    onError: (error) => toasts.error(adminErrorText(t, error)),
  });

  return (
    <div className="flex flex-col gap-4" data-testid="settings-ai-categories">
      <h2 className="type-heading text-text-primary">{t('ai.categoriesAdmin.title')}</h2>
      <p className="type-small text-text-secondary">{t('ai.categoriesAdmin.help')}</p>
      <div className="overflow-x-auto">
        <table className="type-small w-full border-collapse text-text-primary">
          <thead>
            <tr className="border-b border-border-default text-left">
              <th scope="col" className="py-1.5 pr-2 font-medium">
                {t('ai.categoriesAdmin.name')}
              </th>
              <th scope="col" className="px-2 py-1.5 font-medium">
                {t('ai.categoriesAdmin.color')}
              </th>
              <th scope="col" className="px-2 py-1.5 font-medium">
                {t('ai.categoriesAdmin.enabled')} ⚠
              </th>
              <th scope="col" className="px-2 py-1.5 font-medium">
                {t('ai.categoriesAdmin.description')} ⚠
              </th>
              <th scope="col" className="px-2 py-1.5 text-right font-medium">
                {t('ai.categoriesAdmin.count')}
              </th>
              <th scope="col" className="sr-only">
                {t('ai.categoriesAdmin.remove')}
              </th>
            </tr>
          </thead>
          <tbody>
            {drafts.map((d) => {
              const name = d.builtin ? t(`ai.categories.${d.id}.label`, { defaultValue: d.label ?? '' }) : d.label;
              return (
                <tr key={d.key} className="border-b border-border-default align-top" data-testid={`category-${d.key}`}>
                  <th scope="row" className="py-1.5 pr-2 text-left font-normal">
                    {d.builtin ? (
                      name
                    ) : (
                      <input
                        className={INPUT}
                        aria-label={t('ai.categoriesAdmin.name')}
                        maxLength={40}
                        value={d.label ?? ''}
                        onChange={(e) => update(d.key, { label: e.target.value })}
                      />
                    )}
                  </th>
                  <td className="px-2 py-1.5">
                    <select
                      className={INPUT}
                      aria-label={`${t('ai.categoriesAdmin.color')}: ${name ?? ''}`}
                      disabled={d.builtin}
                      value={d.color}
                      onChange={(e) => update(d.key, { color: e.target.value as CategoryColor })}
                    >
                      {COLORS.map((c) => (
                        <option key={c} value={c}>
                          {t(`ai.categoriesAdmin.colors.${c}`)}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="px-2 py-1.5">
                    <input
                      type="checkbox"
                      role="switch"
                      checked={d.enabled}
                      disabled={d.locked}
                      onChange={(e) => update(d.key, { enabled: e.target.checked })}
                      aria-label={`${t('ai.categoriesAdmin.enabled')}: ${name ?? ''}`}
                    />
                  </td>
                  <td className="min-w-[16rem] px-2 py-1.5">
                    <textarea
                      className={INPUT}
                      rows={2}
                      maxLength={300}
                      aria-label={`${t('ai.categoriesAdmin.description')}: ${name ?? ''}`}
                      value={d.description}
                      onChange={(e) => update(d.key, { description: e.target.value })}
                    />
                  </td>
                  <td className="px-2 py-1.5 text-right">{d.count}</td>
                  <td className="py-1.5 pl-2">
                    {d.builtin ? null : (
                      <button
                        type="button"
                        className="text-text-secondary hover:text-text-primary"
                        aria-label={`${t('ai.categoriesAdmin.remove')}: ${name ?? ''}`}
                        onClick={() => setDrafts((all) => all.filter((x) => x.key !== d.key))}
                      >
                        <Trash2 size={16} aria-hidden="true" />
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="type-small text-text-secondary">{t('ai.categoriesAdmin.offHint')}</p>
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          variant="secondary"
          icon={<Plus size={16} aria-hidden="true" />}
          disabled={customCount >= MAX_CUSTOM}
          onClick={() =>
            setDrafts((all) => [
              ...all,
              {
                key: `new-${all.length}`,
                id: null,
                label: '',
                description: '',
                color: 'neutral',
                enabled: true,
                builtin: false,
                locked: false,
                count: 0,
              },
            ])
          }
        >
          {t('ai.categoriesAdmin.add', { count: customCount, max: MAX_CUSTOM })}
        </Button>
        <Button
          type="button"
          icon={<Check size={16} aria-hidden="true" />}
          disabled={save.isPending}
          onClick={() => save.mutate()}
        >
          {t('settings.save')}
        </Button>
      </div>
    </div>
  );
}
