import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ChevronUp, CircleAlert, CircleCheck, ShieldAlert, Sparkles, TriangleAlert, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { Button } from '../../components/Button';
import { Checkbox } from '../../components/Checkbox';
import { useToasts } from '../../components/toastContext';
import { ApiError } from '../../lib/api';
import { day, money } from '../money/moneyApi';
import { CollapsedSuggestion } from './CollapsedSuggestion';
import { approveSuggestion, rejectSuggestion, suggestionsKey, type Suggestion } from './suggestionsApi';
import { FileTypeIcon } from '../../components/FileTypeIcon';

type Props = { suggestion: Suggestion; mailbox: string; messageId: string; readOnly: boolean };

const ICON = {
  ok: <CircleCheck size={16} aria-hidden="true" className="shrink-0 text-success-700" />,
  warning: <TriangleAlert size={16} aria-hidden="true" className="shrink-0 text-warning-700" />,
  blocking: <CircleAlert size={16} aria-hidden="true" className="shrink-0 text-danger-600" />,
  requires_ack: <ShieldAlert size={16} aria-hidden="true" className="shrink-0 text-danger-600" />,
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
  const pick = suggestion.pick === true;
  // #217: in pick mode the person ticks which invoices go with the draft; the ack row follows the picked ones
  const [picked, setPicked] = useState<string[]>(() => invoices.filter((i) => i.selected).map((i) => i.number));
  const chosen = invoices.filter((i) => picked.includes(i.number));
  const chosenForeign = chosen.filter((i) => !i.own);
  const mixed = new Set(chosen.map((i) => (i.own ? 'own' : (i.owner_money_id ?? '')))).size > 1;
  const checks = pick ? suggestion.checks.filter((c) => c.level !== 'requires_ack') : suggestion.checks;
  const blocked = checks.some((c) => c.level === 'blocking');
  const warnings = suggestion.checks.filter((c) => c.level === 'warning' || c.level === 'requires_ack');
  // #215 (ADR-019): another company's invoice — the primary action unlocks only after the person ticks it
  const needsAck = pick
    ? chosenForeign.length > 0 && !mixed
      ? [
          {
            id: 'invoice_other_customer',
            level: 'requires_ack' as const,
            params: {
              owner: chosenForeign[0]?.owner_name ?? '',
              requester: suggestion.company_name || suggestion.to[0] || '',
            } as Record<string, unknown>,
          },
        ]
      : []
    : suggestion.checks.filter((c) => c.level === 'requires_ack');
  const [acked, setAcked] = useState(false);
  const preselected = invoices.filter((i) => i.selected).map((i) => i.number);
  const changedPick = pick && (picked.length !== preselected.length || picked.some((n) => !preselected.includes(n)));
  const toggle = (number: string, on: boolean) => {
    setPicked((now) => (on ? [...now, number] : now.filter((n) => n !== number)));
    setAcked(false); // a new choice needs a new confirmation
  };
  const approve = useMutation({
    mutationFn: () =>
      approveSuggestion(
        suggestion.id,
        null,
        acked ? needsAck.map((c) => c.id) : [],
        pick ? invoices.filter((i) => picked.includes(i.number)).map((i) => i.number) : null,
      ),
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
      className="flex max-w-[760px] flex-col gap-3 rounded-lg border border-ai-200 bg-ai-50 p-4"
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
      {pick ? (
        <fieldset className="flex flex-col gap-1" data-testid="invoice-pick">
          <legend className="type-label mb-1 text-text-primary">{t('ai.invoice.pick.legend')}</legend>
          <ul className="flex flex-col divide-y divide-border-default rounded-sm border border-border-default bg-bg-canvas">
            {invoices.map((i) => (
              <li key={i.id} className="flex flex-col gap-0.5 px-3 py-2" data-testid="invoice-pick-row">
                <div className="type-small flex items-center gap-2 text-text-primary">
                  <Checkbox
                    checked={picked.includes(i.number)}
                    disabled={readOnly}
                    onChange={(e) => toggle(i.number, e.target.checked)}
                    label={<span className="font-medium">{i.number}</span>}
                    data-testid={`invoice-pick-${i.number}`}
                  />
                  <FileTypeIcon type="pdf" />
                  <span className="min-w-0 flex-1 truncate text-text-secondary">
                    {t(i.kind === 'proforma' ? 'ai.invoice.proforma' : 'ai.invoice.invoice')} ·{' '}
                    {t('ai.invoice.pick.issued', { date: day(i.issued_on ?? null) })}
                  </span>
                  <span className="shrink-0 tabular-nums">{money(i.total)}</span>
                </div>
                {!i.own ? (
                  <span className="type-caption ml-6 flex items-center gap-1 text-danger-600">
                    {ICON.blocking}
                    {t('ai.invoice.pick.otherCompany', { owner: i.owner_name ?? '—' })}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
          {mixed ? (
            <p className="type-small flex items-center gap-2 text-danger-600" role="alert">
              {ICON.blocking}
              {t('ai.invoice.pick.oneCustomer')}
            </p>
          ) : picked.length === 0 ? (
            <p className="type-small text-text-secondary">{t('ai.invoice.pick.noneSelected')}</p>
          ) : null}
        </fieldset>
      ) : (
        <ul className="flex flex-col divide-y divide-border-default rounded-sm border border-border-default bg-bg-canvas">
          {invoices.map((i) => (
            <li key={i.id} className="type-small flex items-center gap-2 px-3 py-2 text-text-primary">
              <FileTypeIcon type="pdf" />
              <span className="font-medium">{i.number}</span>
              <span className="min-w-0 flex-1 truncate text-text-secondary">
                {t(i.kind === 'proforma' ? 'ai.invoice.proforma' : 'ai.invoice.invoice')} ·{' '}
                {t('money.customer.dueOn', { date: day(i.due_on) })}
              </span>
              <span className="shrink-0 tabular-nums">{money(i.remaining)}</span>
            </li>
          ))}
        </ul>
      )}
      <ul className="flex flex-col">
        {[...checks.filter((c) => c.level !== 'requires_ack'), ...needsAck].map((c, n) =>
          c.level === 'requires_ack' ? (
            <li
              key={`${c.id}-${n}`}
              className="type-small my-1 flex flex-col gap-2 rounded-sm border border-danger-600 bg-danger-50 px-3 py-2"
              data-testid="invoice-ack"
            >
              <span className="flex items-center gap-2 font-medium text-danger-600">
                {ICON.requires_ack}
                {t('ai.invoice.checks.invoice_other_customer_ack', {
                  owner: String(c.params.owner ?? ''),
                  requester: String(c.params.requester ?? ''),
                })}
              </span>
              <Checkbox
                checked={acked}
                disabled={readOnly}
                onChange={(e) => setAcked(e.target.checked)}
                label={t('ai.invoice.ackLabel')}
                data-testid="invoice-ack-checkbox"
              />
            </li>
          ) : (
            <li key={`${c.id}-${n}`} className="type-small flex min-h-7 items-center gap-2 text-text-primary">
              {ICON[c.level]}
              <span>{checkText(c.id, c.params)}</span>
            </li>
          ),
        )}
      </ul>
      <p className="type-body whitespace-pre-wrap rounded-sm border border-border-default bg-bg-canvas p-3 text-text-primary">
        {suggestion.body}
      </p>
      {changedPick ? <p className="type-caption text-text-secondary">{t('ai.invoice.pick.bodyChanges')}</p> : null}
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          disabled={
            readOnly ||
            blocked ||
            approve.isPending ||
            invoices.length === 0 ||
            (pick && (picked.length === 0 || mixed)) ||
            (needsAck.length > 0 && !acked)
          }
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
      <p className="type-caption text-text-secondary">
        {needsAck.length > 0
          ? t('ai.invoice.footerForeign', { owner: String(needsAck[0]?.params.owner ?? '') })
          : t('ai.invoice.footer')}
      </p>
    </section>
  );
}
