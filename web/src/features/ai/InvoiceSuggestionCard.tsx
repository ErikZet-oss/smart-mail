import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ChevronUp, CircleAlert, CircleCheck, FileText, Sparkles, TriangleAlert, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { Button } from '../../components/Button';
import { useToasts } from '../../components/toastContext';
import { ApiError } from '../../lib/api';
import { day, money } from '../money/moneyApi';
import { CollapsedSuggestion } from './CollapsedSuggestion';
import { approveSuggestion, rejectSuggestion, suggestionsKey, type Suggestion } from './suggestionsApi';

type Props = { suggestion: Suggestion; mailbox: string; messageId: string; readOnly: boolean };

const ICON = {
  ok: <CircleCheck size={16} aria-hidden="true" className="shrink-0 text-success-700" />,
  warning: <TriangleAlert size={16} aria-hidden="true" className="shrink-0 text-warning-700" />,
  blocking: <CircleAlert size={16} aria-hidden="true" className="shrink-0 text-danger-600" />,
} as const;

/**
 * Phase 3d `invoice_attach` (UX_SPEC §3.1): the customer asked for an invoice copy. „Pripraviť koncept s faktúrou“
 * re-checks everything in Money and prepares a reply draft with Money's original PDF — sending stays with the person
 * (level 2). Collapsed by default like every suggestion card (#156).
 */
export function InvoiceSuggestionCard({ suggestion, mailbox, messageId, readOnly }: Props) {
  const { t } = useTranslation();
  const toasts = useToasts();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const headerToggle = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (open) headerToggle.current?.focus();
  }, [open]);
  const done = () => void qc.invalidateQueries({ queryKey: suggestionsKey(mailbox, messageId) });
  const invoices = suggestion.invoices ?? [];
  const blocked = suggestion.blocked || suggestion.checks.some((c) => c.level === 'blocking');
  const warnings = suggestion.checks.filter((c) => c.level === 'warning');
  const approve = useMutation({
    mutationFn: () => approveSuggestion(suggestion.id, null),
    onSuccess: (out) => {
      toasts.success(t('ai.invoice.drafted'));
      done();
      navigate(`/compose/${out.draft_id}?mailbox=${encodeURIComponent(mailbox)}`);
    },
    onError: (error) => {
      const code = error instanceof ApiError ? error.detail.code : 'generic';
      toasts.error(t(`ai.invoice.errors.${code}`, { defaultValue: t('mail.errors.generic') }));
      done();
    },
  });
  const reject = useMutation({
    mutationFn: () => rejectSuggestion(suggestion.id, ['not_needed'], null),
    onSuccess: () => {
      toasts.success(t('ai.card.rejected'));
      done();
    },
    onError: () => toasts.error(t('mail.errors.generic')),
  });
  const numbers = invoices.map((i) => i.number).join(', ');
  const checkText = (id: string, params: Record<string, unknown>) =>
    t(`ai.invoice.checks.${id}`, { ...params, defaultValue: t('ai.card.checks.unknown', { id }) });

  if (!open) {
    return (
      <CollapsedSuggestion
        title={t('ai.invoice.title')}
        subline={suggestion.company_name ?? ''}
        status={blocked ? 'blocked' : warnings.length > 0 ? 'warning' : 'ok'}
        warnings={warnings.length}
        preview={numbers}
        testId="ai-invoice-card"
        onExpand={() => setOpen(true)}
        onReject={readOnly ? undefined : () => reject.mutate()}
        rejectDisabled={reject.isPending}
      />
    );
  }
  return (
    <section
      aria-label={t('ai.invoice.title')}
      data-testid="ai-invoice-card"
      data-collapsed="false"
      className={`flex max-w-[760px] flex-col gap-3 rounded-lg border bg-ai-50 p-4 ${
        blocked ? 'border-danger-600' : warnings.length ? 'border-warning-600' : 'border-success-600'
      }`}
    >
      <header className="flex items-start gap-2">
        <Sparkles size={18} aria-hidden="true" className="mt-0.5 shrink-0 text-ai-600" />
        <div className="min-w-0 flex-1">
          <h2 className="type-heading text-text-primary">{t('ai.invoice.title')}</h2>
          <p className="type-small text-text-secondary">
            {t('ai.invoice.subline', { company: suggestion.company_name ?? '', to: suggestion.to.join(', ') })}
          </p>
        </div>
        <button
          ref={headerToggle}
          type="button"
          aria-expanded={true}
          onClick={() => setOpen(false)}
          className="type-small inline-flex h-8 shrink-0 items-center gap-1 rounded-sm px-2 text-text-secondary hover:bg-bg-muted"
        >
          <ChevronUp size={16} aria-hidden="true" />
          {t('ai.card.collapsed.hide')}
        </button>
      </header>
      <ul className="flex flex-col divide-y divide-border-default rounded-sm border border-border-default bg-bg-canvas">
        {invoices.map((i) => (
          <li key={i.id} className="type-small flex items-center gap-2 px-3 py-2 text-text-primary">
            <FileText size={16} aria-hidden="true" className="shrink-0 text-text-secondary" />
            <span className="font-medium">{i.number}</span>
            <span className="min-w-0 flex-1 truncate text-text-secondary">
              {t(i.kind === 'proforma' ? 'ai.invoice.proforma' : 'ai.invoice.invoice')} ·{' '}
              {t('money.customer.dueOn', { date: day(i.due_on) })}
            </span>
            <span className="shrink-0 tabular-nums">{money(i.remaining)}</span>
          </li>
        ))}
      </ul>
      <ul className="flex flex-col">
        {suggestion.checks.map((c, n) => (
          <li key={`${c.id}-${n}`} className="type-small flex min-h-7 items-center gap-2 text-text-primary">
            {ICON[c.level]}
            <span>{checkText(c.id, c.params)}</span>
          </li>
        ))}
      </ul>
      <p className="type-body whitespace-pre-wrap rounded-sm border border-border-default bg-bg-canvas p-3 text-text-primary">
        {suggestion.body}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          disabled={readOnly || blocked || approve.isPending || invoices.length === 0}
          onClick={() => approve.mutate()}
          icon={<CircleCheck size={16} aria-hidden="true" />}
        >
          {t('ai.invoice.approve')}
        </Button>
        <button
          type="button"
          disabled={readOnly || reject.isPending}
          onClick={() => reject.mutate()}
          className="type-label inline-flex h-8 items-center gap-1 rounded-sm px-3 text-text-secondary hover:bg-bg-muted disabled:opacity-60"
        >
          <X size={16} aria-hidden="true" />
          {t('ai.card.reject')}
        </button>
      </div>
      <p className="type-caption text-text-secondary">{t('ai.invoice.footer')}</p>
    </section>
  );
}
