import type { Editor } from '@tiptap/core';
import { useMutation } from '@tanstack/react-query';
import { Sparkles } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '../../components/Button';
import { ApiError } from '../../lib/api';
import { replaceUserText, userTextOf, wordDiff } from './aiText';
import { composeAi, type AiAction, type AiLanguage, type AiProposal } from './composeApi';

const CHIPS: AiAction[] = ['shorter', 'formal', 'friendly', 'grammar', 'answer_all'];
const LANGUAGES: AiLanguage[] = ['sk', 'cs', 'en', 'de', 'pl', 'hu'];

type Props = { draftId: string | null; editor: Editor | null; disabled: boolean; onApplied?: () => void };

/**
 * W4a / M17 compose AI panel (Phase 2d): Napíš za mňa, rewrite chips, Preložiť do…, Doplniť odpoveď na všetky otázky.
 * Every result is a diff of the person's own text with „Použiť“ / „Zahodiť“; the quote and the signature are never
 * sent to the model nor replaced.
 */
export function ComposeAiPanel({ draftId, editor, disabled, onApplied }: Props) {
  const { t } = useTranslation();
  const [instruction, setInstruction] = useState('');
  const [language, setLanguage] = useState<AiLanguage>('en');
  const [before, setBefore] = useState('');
  const [proposal, setProposal] = useState<AiProposal | null>(null);
  const [hint, setHint] = useState<string | null>(null);

  const run = useMutation({
    mutationFn: (input: { action: AiAction; text: string; instruction?: string; language?: AiLanguage }) => {
      if (!draftId) return Promise.reject(new Error('draft missing'));
      return composeAi(draftId, input);
    },
    onSuccess: (out) => setProposal(out),
    onError: (error) => {
      const code = error instanceof ApiError ? String(error.detail.code ?? '') : '';
      setHint(
        t(
          code === 'ai_unavailable' || code === 'ai_budget_exceeded'
            ? `ai.compose.errors.${code}`
            : 'ai.compose.errors.generic',
        ),
      );
    },
  });

  const start = (action: AiAction, extra: { instruction?: string; language?: AiLanguage } = {}) => {
    const text = userTextOf(editor);
    setHint(null);
    setProposal(null);
    if (action !== 'write' && !text) {
      setHint(t('ai.compose.emptyText'));
      return;
    }
    setBefore(text);
    run.mutate({ action, text, ...extra });
  };

  const busy = disabled || run.isPending || !draftId;

  return (
    <div data-testid="compose-ai-panel" className="flex flex-col gap-4">
      <label className="flex flex-col gap-1.5">
        <span className="type-label text-text-secondary">{t('ai.compose.writeLabel')}</span>
        <textarea
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          rows={3}
          maxLength={2000}
          placeholder={t('ai.compose.writePlaceholder')}
          className="type-body rounded-sm border border-border-default bg-bg-canvas p-2 text-text-primary"
        />
      </label>
      <Button
        type="button"
        className="self-start"
        disabled={busy || !instruction.trim()}
        onClick={() => start('write', { instruction: instruction.trim() })}
        icon={<Sparkles size={16} aria-hidden="true" />}
      >
        {t('ai.compose.write')}
      </Button>

      <div className="flex flex-col gap-1.5">
        <span className="type-label text-text-secondary">{t('ai.compose.rewrite')}</span>
        <div className="flex flex-wrap gap-2">
          {CHIPS.map((action) => (
            <button
              key={action}
              type="button"
              disabled={busy}
              onClick={() => start(action)}
              className="type-small h-7 rounded-full border border-border-default bg-bg-canvas px-3 text-text-primary hover:bg-bg-muted disabled:opacity-60"
            >
              {t(`ai.compose.actions.${action}`)}
            </button>
          ))}
        </div>
      </div>

      <div className="flex items-end gap-2">
        <label className="flex flex-1 flex-col gap-1.5">
          <span className="type-label text-text-secondary">{t('ai.compose.translateLabel')}</span>
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value as AiLanguage)}
            className="type-body h-8 rounded-sm border border-border-default bg-bg-canvas px-2"
          >
            {LANGUAGES.map((code) => (
              <option key={code} value={code}>
                {t(`ai.compose.languages.${code}`)}
              </option>
            ))}
          </select>
        </label>
        <Button type="button" variant="secondary" disabled={busy} onClick={() => start('translate', { language })}>
          {t('ai.compose.translate')}
        </Button>
      </div>

      {run.isPending ? (
        <p role="status" className="type-small text-ai-600">
          {t('ai.compose.loading')}
        </p>
      ) : null}
      {hint ? (
        <p role="alert" className="type-small text-danger-600">
          {hint}
        </p>
      ) : null}

      {proposal ? (
        <section
          aria-label={t('ai.compose.proposal')}
          data-testid="compose-ai-proposal"
          className="flex flex-col gap-3 rounded-lg border border-ai-600 bg-ai-50 p-3"
        >
          <h3 className="type-label text-text-primary">{t('ai.compose.proposal')}</h3>
          <p className="type-body whitespace-pre-wrap rounded-sm bg-bg-canvas p-2 text-text-primary">
            {wordDiff(before, proposal.text).map((part, i) =>
              part.kind === 'same' ? (
                <span key={i}>{part.text}</span>
              ) : part.kind === 'added' ? (
                <ins key={i} className="bg-success-50 text-success-700 no-underline">
                  {part.text}
                </ins>
              ) : (
                <del key={i} className="bg-danger-50 text-danger-600">
                  {part.text}
                </del>
              ),
            )}
          </p>
          {proposal.unanswered.length > 0 ? (
            <div className="type-small text-text-primary">
              <p>{t('ai.compose.unanswered')}</p>
              <ul className="ml-4 list-disc">
                {proposal.unanswered.map((q) => (
                  <li key={q}>{q}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {proposal.placeholders.length > 0 ? (
            <p className="type-small text-warning-700">{t('ai.compose.placeholders')}</p>
          ) : null}
          <div className="flex gap-2">
            <Button
              type="button"
              disabled={!editor}
              onClick={() => {
                if (!editor) return;
                replaceUserText(editor, proposal.text);
                setProposal(null);
                onApplied?.();
              }}
            >
              {t('ai.compose.apply')}
            </Button>
            <Button type="button" variant="secondary" onClick={() => setProposal(null)}>
              {t('ai.compose.discard')}
            </Button>
          </div>
        </section>
      ) : null}

      <p className="type-caption text-text-secondary">{t('ai.compose.footer')}</p>
    </div>
  );
}
