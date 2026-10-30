import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, Pencil, SquarePlus, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '../../components/Button';
import { ConfirmDialog } from '../../components/Dialog';
import { Switch } from '../../components/Switch';
import { useToasts } from '../../components/toastContext';
import { adminErrorText, INPUT } from './adminUi';
import {
  createKnowledge,
  deleteKnowledge,
  fetchKnowledge,
  fetchStyleGuide,
  knowledgeKey,
  saveStyleGuide,
  styleGuideKey,
  updateKnowledge,
  type KnowledgeCardIn,
  type KnowledgeCardOut,
} from './settingsApi';

const EMPTY: KnowledgeCardIn = { title: '', body: '', valid_until: null, tags: [], enabled: true };

function toForm(card: KnowledgeCardOut): KnowledgeCardIn {
  return {
    title: card.title,
    body: card.body,
    valid_until: card.valid_until,
    tags: card.tags,
    enabled: card.enabled,
  };
}

/** W12-17d Štýl a znalosti (admin, Phase 2e): the company style guide and the knowledge cards used in AI drafts. */
export function AiKnowledgePanel() {
  return (
    <div className="flex max-w-[var(--layout-settings-form-max)] flex-col gap-8" data-testid="settings-ai-knowledge">
      <StyleGuide />
      <KnowledgeCards />
    </div>
  );
}

function StyleGuide() {
  const { t } = useTranslation();
  const toasts = useToasts();
  const queryClient = useQueryClient();
  const guide = useQuery({ queryKey: styleGuideKey, queryFn: fetchStyleGuide });
  const [draft, setDraft] = useState<string | null>(null);
  const value = draft ?? guide.data?.body ?? '';
  const save = useMutation({
    mutationFn: () => saveStyleGuide(value),
    onSuccess: (out) => {
      queryClient.setQueryData(styleGuideKey, out);
      setDraft(null);
      toasts.success(t('ai.admin.saved'));
    },
    onError: (error) => toasts.error(adminErrorText(t, error)),
  });
  return (
    <section className="flex flex-col gap-2" aria-labelledby="ai-style-title">
      <h2 id="ai-style-title" className="type-heading text-text-primary">
        {t('ai.admin.styleTitle')}
      </h2>
      <p className="type-small text-text-secondary">{t('ai.admin.styleHelp')}</p>
      <label className="flex flex-col gap-1">
        <span className="type-label text-text-secondary">{t('ai.admin.styleLabel')}</span>
        <textarea
          value={value}
          onChange={(e) => setDraft(e.target.value)}
          rows={8}
          maxLength={20000}
          className={`${INPUT} h-auto py-2`}
        />
      </label>
      <Button
        type="button"
        className="self-start"
        icon={<Check size={16} aria-hidden="true" />}
        disabled={save.isPending || draft === null}
        onClick={() => save.mutate()}
      >
        {t('ai.admin.save')}
      </Button>
    </section>
  );
}

function KnowledgeCards() {
  const { t } = useTranslation();
  const toasts = useToasts();
  const queryClient = useQueryClient();
  const cards = useQuery({ queryKey: knowledgeKey, queryFn: fetchKnowledge });
  const [editing, setEditing] = useState<{ id: string | null; form: KnowledgeCardIn } | null>(null);
  const [tagsText, setTagsText] = useState('');
  const [deleting, setDeleting] = useState<KnowledgeCardOut | null>(null);
  const refresh = () => void queryClient.invalidateQueries({ queryKey: knowledgeKey });

  const save = useMutation({
    mutationFn: () => {
      if (!editing) return Promise.reject(new Error('nothing to save'));
      const form = {
        ...editing.form,
        tags: tagsText
          .split(',')
          .map((x) => x.trim())
          .filter(Boolean),
      };
      return editing.id ? updateKnowledge(editing.id, form) : createKnowledge(form);
    },
    onSuccess: () => {
      setEditing(null);
      refresh();
      toasts.success(t('ai.admin.saved'));
    },
    onError: (error) => toasts.error(adminErrorText(t, error)),
  });
  const remove = useMutation({
    mutationFn: (id: string) => deleteKnowledge(id),
    onSuccess: () => {
      setDeleting(null);
      refresh();
    },
    onError: (error) => toasts.error(adminErrorText(t, error)),
  });

  const open = (card: KnowledgeCardOut | null) => {
    setEditing({ id: card?.id ?? null, form: card ? toForm(card) : EMPTY });
    setTagsText(card?.tags.join(', ') ?? '');
  };
  const set = (patch: Partial<KnowledgeCardIn>) =>
    setEditing((prev) => (prev ? { ...prev, form: { ...prev.form, ...patch } } : prev));

  return (
    <section className="flex flex-col gap-3" aria-labelledby="ai-knowledge-title">
      <div className="flex items-center justify-between gap-2">
        <h2 id="ai-knowledge-title" className="type-heading text-text-primary">
          {t('ai.admin.knowledgeTitle')}
        </h2>
        <Button
          type="button"
          variant="secondary"
          icon={<SquarePlus size={16} aria-hidden="true" />}
          onClick={() => open(null)}
        >
          {t('ai.admin.add')}
        </Button>
      </div>
      <p className="type-small text-text-secondary">{t('ai.admin.knowledgeHelp')}</p>

      {editing ? (
        <form
          className="flex flex-col gap-3 rounded-md border border-border-default p-4"
          aria-label={t('ai.admin.add')}
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <label className="flex flex-col gap-1">
            <span className="type-label text-text-secondary">{t('ai.admin.form.title')}</span>
            <input
              value={editing.form.title}
              onChange={(e) => set({ title: e.target.value })}
              maxLength={200}
              required
              className={INPUT}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="type-label text-text-secondary">{t('ai.admin.form.body')}</span>
            <textarea
              value={editing.form.body}
              onChange={(e) => set({ body: e.target.value })}
              rows={6}
              maxLength={20000}
              required
              className={`${INPUT} h-auto py-2`}
            />
          </label>
          <div className="flex flex-wrap gap-3">
            <label className="flex flex-col gap-1">
              <span className="type-label text-text-secondary">{t('ai.admin.form.validUntil')}</span>
              <input
                type="date"
                value={editing.form.valid_until ?? ''}
                onChange={(e) => set({ valid_until: e.target.value || null })}
                className={INPUT}
              />
            </label>
            <label className="flex min-w-[220px] flex-1 flex-col gap-1">
              <span className="type-label text-text-secondary">{t('ai.admin.form.tags')}</span>
              <input value={tagsText} onChange={(e) => setTagsText(e.target.value)} className={INPUT} />
            </label>
          </div>
          <Switch
            checked={editing.form.enabled}
            onChange={(enabled) => set({ enabled })}
            label={t('ai.admin.form.enabled')}
          />
          <div className="flex gap-2">
            <Button type="submit" disabled={save.isPending}>
              {t('ai.admin.form.save')}
            </Button>
            <Button type="button" variant="secondary" onClick={() => setEditing(null)}>
              {t('ai.admin.form.cancel')}
            </Button>
          </div>
        </form>
      ) : null}

      {cards.data && cards.data.length === 0 ? (
        <p className="type-small text-text-secondary">{t('ai.admin.empty')}</p>
      ) : (
        <div className="overflow-x-auto" tabIndex={0} role="region" aria-labelledby="ai-knowledge-title">
          <table className="type-small w-full text-left">
            <thead className="text-text-secondary">
              <tr className="border-b border-border-default">
                <th className="py-2 pr-3 font-semibold">{t('ai.admin.cols.title')}</th>
                <th className="py-2 pr-3 font-semibold">{t('ai.admin.cols.validUntil')}</th>
                <th className="py-2 pr-3 font-semibold">{t('ai.admin.cols.tags')}</th>
                <th className="py-2 pr-3 font-semibold">{t('ai.admin.cols.enabled')}</th>
                <th className="py-2" aria-label={t('ai.admin.edit')} />
              </tr>
            </thead>
            <tbody>
              {(cards.data ?? []).map((card) => (
                <tr key={card.id} className="border-b border-border-default text-text-primary">
                  <td className="py-2 pr-3">{card.title}</td>
                  <td className="py-2 pr-3">
                    {card.valid_until ?? t('ai.admin.never')}
                    {card.expired ? <span className="ml-1 text-danger-600">({t('ai.admin.expired')})</span> : null}
                  </td>
                  <td className="py-2 pr-3">{card.tags.join(', ')}</td>
                  <td className="py-2 pr-3">{t(card.enabled ? 'ai.admin.on' : 'ai.admin.off')}</td>
                  <td className="py-2 text-right whitespace-nowrap">
                    <button
                      type="button"
                      className="rounded-sm p-1.5 text-text-secondary hover:bg-bg-muted"
                      aria-label={`${t('ai.admin.edit')}: ${card.title}`}
                      onClick={() => open(card)}
                    >
                      <Pencil size={16} aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      className="rounded-sm p-1.5 text-danger-600 hover:bg-bg-muted"
                      aria-label={`${t('ai.admin.delete')}: ${card.title}`}
                      onClick={() => setDeleting(card)}
                    >
                      <Trash2 size={16} aria-hidden="true" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {deleting ? (
        <ConfirmDialog
          title={t('ai.admin.deleteTitle', { title: deleting.title })}
          body={t('ai.admin.deleteBody')}
          confirmLabel={t('ai.admin.delete')}
          busy={remove.isPending}
          onConfirm={() => remove.mutate(deleting.id)}
          onClose={() => setDeleting(null)}
        />
      ) : null}
    </section>
  );
}
