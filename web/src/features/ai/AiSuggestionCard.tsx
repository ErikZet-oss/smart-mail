import { useMutation, useQueryClient } from '@tanstack/react-query';
import { CircleAlert, CircleCheck, Pencil, Sparkles, TriangleAlert, X } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { Button } from '../../components/Button';
import { useToasts } from '../../components/toastContext';
import { ApiError } from '../../lib/api';
import { cardChecks, cardState, type CardCheck, type CardState } from './cardChecks';
import {
  approveSuggestion,
  REJECT_REASONS,
  rejectSuggestion,
  suggestionsKey,
  type RejectReason,
  type Suggestion,
} from './suggestionsApi';

const VISIBLE_CHECKS = 4;

const BORDER: Record<CardState, string> = {
  blocked: 'border-danger-600',
  attention: 'border-warning-600',
  lowconf: 'border-border-strong',
  ready: 'border-success-600',
};

const ICON = {
  ok: <CircleCheck size={16} aria-hidden="true" className="shrink-0 text-success-700" />,
  warning: <TriangleAlert size={16} aria-hidden="true" className="shrink-0 text-warning-700" />,
  blocking: <CircleAlert size={16} aria-hidden="true" className="shrink-0 text-danger-600" />,
} as const;

type Props = {
  suggestion: Suggestion;
  mailbox: string;
  messageId: string;
  category: string | null;
  readOnly: boolean;
};

/**
 * UX_SPEC §3.1 `AiSuggestionCard`, type `reply` (Phase 2c): checks, draft preview, Pripraviť koncept / Upraviť /
 * Zamietnuť. Approving prepares a draft in Koncepty and opens it in W4 — nothing is sent from here (level 2).
 */
export function AiSuggestionCard({ suggestion, mailbox, messageId, category, readOnly }: Props) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toasts = useToasts();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(suggestion.body);
  const [expanded, setExpanded] = useState(false);
  const [allChecks, setAllChecks] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [reasons, setReasons] = useState<RejectReason[]>([]);
  const [note, setNote] = useState('');

  const state = cardState(suggestion);
  const checks = cardChecks(suggestion);
  const shown = allChecks ? checks : checks.slice(0, VISIBLE_CHECKS);
  const edited = text.trim() !== suggestion.body.trim();
  const done = () => void queryClient.invalidateQueries({ queryKey: suggestionsKey(mailbox, messageId) });

  const approve = useMutation({
    mutationFn: () => approveSuggestion(suggestion.id, edited ? text : null),
    onSuccess: (out) => {
      toasts.success(t('ai.card.drafted'));
      done();
      navigate(`/compose/${out.draft_id}?mailbox=${encodeURIComponent(mailbox)}`);
    },
    onError: (error) => {
      const blocked = error instanceof ApiError && error.detail.code === 'suggestion_blocked';
      toasts.error(t(blocked ? 'ai.card.blockedToast' : 'mail.errors.generic'));
      done();
    },
  });
  const reject = useMutation({
    mutationFn: () => rejectSuggestion(suggestion.id, reasons, note.trim() || null),
    onSuccess: () => {
      toasts.success(t('ai.card.rejected'));
      done();
    },
    onError: () => toasts.error(t('mail.errors.generic')),
  });

  const checkText = (c: CardCheck) =>
    t(`ai.card.checks.${c.key}`, { ...c.params, defaultValue: t('ai.card.checks.unknown', { id: c.key }) });
  const subline = t('ai.card.subline', {
    category: category ? t(`ai.categories.${category}.label`, { defaultValue: category }) : '',
    language: t(`ai.card.languages.${suggestion.language ?? 'other'}`, { defaultValue: suggestion.language ?? '' }),
  });
  const busy = approve.isPending || reject.isPending;

  return (
    <section
      aria-label={t('ai.card.replyTitle')}
      data-testid="ai-suggestion-card"
      data-state={state}
      className={`flex max-w-[760px] flex-col gap-3 rounded-lg border bg-ai-50 p-4 ${BORDER[state]}`}
    >
      <header className="flex items-start gap-2">
        <Sparkles size={18} aria-hidden="true" className="mt-0.5 shrink-0 text-ai-600" />
        <div className="min-w-0 flex-1">
          <h2 className="type-heading text-text-primary">{t('ai.card.replyTitle')}</h2>
          <p className="type-small text-text-secondary">{subline}</p>
        </div>
      </header>

      {state === 'lowconf' ? <p className="type-small text-text-secondary">{t('ai.card.lowconf')}</p> : null}

      <ul className="flex flex-col">
        {shown.map((c) => (
          <li key={c.key} className="type-small flex min-h-7 items-center gap-2 text-text-primary">
            {ICON[c.level]}
            <span>{checkText(c)}</span>
          </li>
        ))}
      </ul>
      {checks.length > VISIBLE_CHECKS && !allChecks ? (
        <button
          type="button"
          className="type-small self-start text-brand-primary-700 hover:underline"
          onClick={() => setAllChecks(true)}
        >
          {t('ai.card.moreChecks', { count: checks.length - VISIBLE_CHECKS })}
        </button>
      ) : null}

      {editing ? (
        <label className="flex flex-col gap-1">
          <span className="type-label text-text-secondary">{t('ai.card.editLabel')}</span>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={8}
            className="type-body rounded-sm border border-border-default bg-bg-canvas p-2 text-text-primary"
          />
        </label>
      ) : (
        <div className="rounded-sm border border-border-default bg-bg-canvas p-3">
          <p
            data-testid="ai-draft-preview"
            className={`type-body whitespace-pre-wrap text-text-primary ${expanded ? '' : 'line-clamp-6'}`}
          >
            {text}
          </p>
          <button
            type="button"
            className="type-small mt-1 text-brand-primary-700 hover:underline"
            onClick={() => setExpanded((v) => !v)}
          >
            {t(expanded ? 'ai.card.showLess' : 'ai.card.showAll')}
          </button>
        </div>
      )}

      {suggestion.rationale ? (
        <p className="type-small text-text-secondary">{t('ai.card.rationale', { text: suggestion.rationale })}</p>
      ) : null}

      {rejecting ? (
        <fieldset className="flex flex-col gap-2">
          <legend className="type-label mb-1 text-text-secondary">{t('ai.card.rejectTitle')}</legend>
          <div className="flex flex-wrap gap-2">
            {REJECT_REASONS.map((reason) => {
              const on = reasons.includes(reason);
              return (
                <button
                  key={reason}
                  type="button"
                  aria-pressed={on}
                  onClick={() => setReasons((prev) => (on ? prev.filter((r) => r !== reason) : [...prev, reason]))}
                  className={`type-small h-7 rounded-full border px-3 ${
                    on
                      ? 'border-brand-primary-600 bg-brand-primary-50 text-brand-primary-700'
                      : 'border-border-default bg-bg-canvas text-text-primary hover:bg-bg-muted'
                  }`}
                >
                  {t(`ai.card.reasons.${reason}`)}
                </button>
              );
            })}
          </div>
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            maxLength={500}
            aria-label={t('ai.card.rejectNote')}
            placeholder={t('ai.card.rejectNote')}
            className="type-body h-8 rounded-sm border border-border-default bg-bg-canvas px-2"
          />
          <div className="flex gap-2">
            <Button type="button" variant="secondary" disabled={busy} onClick={() => reject.mutate()}>
              {t('ai.card.rejectConfirm')}
            </Button>
            <Button type="button" variant="secondary" onClick={() => setRejecting(false)}>
              {t('ai.card.rejectCancel')}
            </Button>
          </div>
        </fieldset>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            disabled={readOnly || busy || (state === 'blocked' && !edited)}
            onClick={() => approve.mutate()}
            icon={<CircleCheck size={16} aria-hidden="true" />}
          >
            {t(edited ? 'ai.card.approveEdited' : 'ai.card.approve')}
          </Button>
          <Button
            type="button"
            variant="secondary"
            disabled={readOnly || busy}
            aria-pressed={editing}
            onClick={() => setEditing((v) => !v)}
            icon={<Pencil size={16} aria-hidden="true" />}
          >
            {t(editing ? 'ai.card.editDone' : 'ai.card.edit')}
          </Button>
          <button
            type="button"
            disabled={readOnly || busy}
            onClick={() => setRejecting(true)}
            className="type-label inline-flex h-8 items-center gap-1 rounded-sm px-3 text-text-secondary hover:bg-bg-muted disabled:opacity-60"
          >
            <X size={16} aria-hidden="true" />
            {t('ai.card.reject')}
          </button>
        </div>
      )}

      <p className="type-caption text-text-secondary">{t('ai.card.footer')}</p>
    </section>
  );
}
