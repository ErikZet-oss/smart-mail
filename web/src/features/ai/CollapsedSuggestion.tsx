import { ChevronDown, CircleAlert, CircleCheck, Sparkles, TriangleAlert, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';

export type CollapsedStatus = 'ok' | 'warning' | 'blocked';

const PREVIEW_CHARS = 80;

type Props = {
  title: string;
  subline: string;
  status: CollapsedStatus;
  warnings: number;
  preview: string;
  testId: string;
  onExpand: () => void;
  /** „Zamietnuť“ is allowed while collapsed (#156); approving is not — the person must see the suggestion first. */
  onReject?: () => void;
  rejectDisabled?: boolean;
};

/** #156: one-line collapsed state of an AI suggestion card (built from the existing card — no Figma frame). */
export function CollapsedSuggestion({
  title,
  subline,
  status,
  warnings,
  preview,
  testId,
  onExpand,
  onReject,
  rejectDisabled,
}: Props) {
  const { t } = useTranslation();
  const short = preview.replace(/\s+/g, ' ').trim();
  const clipped = short.length > PREVIEW_CHARS ? `${short.slice(0, PREVIEW_CHARS)}…` : short;
  const statusLabel =
    status === 'blocked'
      ? t('ai.card.collapsed.blocked')
      : status === 'warning'
        ? t('ai.card.collapsed.warnings', { count: warnings })
        : t('ai.card.collapsed.ok');
  return (
    <section
      aria-label={title}
      data-testid={testId}
      data-collapsed="true"
      className="flex min-h-12 max-w-[760px] items-center gap-1 rounded-lg border border-ai-200 bg-ai-50 pr-1"
    >
      <button
        type="button"
        aria-expanded={false}
        onClick={onExpand}
        className="flex min-h-12 min-w-0 flex-1 items-center gap-2 rounded-lg px-3 text-left hover:bg-ai-100 focus-visible:outline-2"
      >
        <Sparkles size={16} aria-hidden="true" className="shrink-0 text-ai-600" />
        <span className="type-label shrink-0 text-text-primary">{title}</span>
        {subline ? <span className="type-small hidden shrink-0 text-text-secondary sm:inline">· {subline}</span> : null}
        <span className="type-small inline-flex shrink-0 items-center gap-1" title={statusLabel}>
          {status === 'blocked' ? (
            <CircleAlert size={16} aria-hidden="true" className="text-danger-600" />
          ) : status === 'warning' ? (
            <TriangleAlert size={16} aria-hidden="true" className="text-warning-700" />
          ) : (
            <CircleCheck size={16} aria-hidden="true" className="text-success-700" />
          )}
          {status === 'warning' ? <span className="text-warning-700">{warnings}</span> : null}
          <span className="sr-only">{statusLabel}</span>
        </span>
        <span className="type-small min-w-0 flex-1 truncate text-text-secondary">{clipped}</span>
        <span className="type-small hidden shrink-0 items-center gap-1 text-brand-primary-700 sm:inline-flex">
          {t('ai.card.collapsed.show')}
        </span>
        <ChevronDown size={16} aria-hidden="true" className="shrink-0 text-text-secondary" />
      </button>
      {onReject ? (
        <button
          type="button"
          onClick={onReject}
          disabled={rejectDisabled}
          aria-label={t('ai.card.reject')}
          title={t('ai.card.reject')}
          className="inline-flex size-8 shrink-0 items-center justify-center rounded-sm text-text-secondary hover:bg-bg-muted disabled:opacity-60"
        >
          <X size={16} aria-hidden="true" />
        </button>
      ) : null}
    </section>
  );
}
