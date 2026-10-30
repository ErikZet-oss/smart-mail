import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ChevronUp, FileCheck2, Sparkles, TriangleAlert } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '../../components/Button';
import { useToasts } from '../../components/toastContext';
import { ConformityDialog } from '../documents/ConformityDialog';
import { CollapsedSuggestion } from './CollapsedSuggestion';
import { rejectSuggestion, suggestionsKey, type Suggestion } from './suggestionsApi';

type Props = { suggestion: Suggestion; mailbox: string; messageId: string; readOnly: boolean };

/** #139 C: the AI only prefills the Prehlásenie o zhode; „Pripraviť prehlásenie…“ opens the dialog and the person
 * checks and issues it (autonomy level 2 — the card has no approve of its own). */
export function ConformitySuggestionCard({ suggestion, mailbox, messageId, readOnly }: Props) {
  const { t } = useTranslation();
  const toasts = useToasts();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState(false); // #156: collapsed by default
  const headerToggle = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (expanded) headerToggle.current?.focus(); // keyboard focus stays on the card header (#156)
  }, [expanded]);
  const form = suggestion.conformity ?? { customer: '', document_ref: '', items: [] };
  const done = () => void queryClient.invalidateQueries({ queryKey: suggestionsKey(mailbox, messageId) });
  const reject = useMutation({
    mutationFn: () => rejectSuggestion(suggestion.id, ['not_needed'], null),
    onSuccess: () => {
      toasts.success(t('ai.card.rejected'));
      done();
    },
    onError: () => toasts.error(t('mail.errors.generic')),
  });
  const warnings = suggestion.checks.filter((c) => c.level !== 'ok');
  if (!expanded) {
    return (
      <CollapsedSuggestion
        title={t('conformity.card.title')}
        subline=""
        status={warnings.length > 0 ? 'warning' : 'ok'}
        warnings={warnings.length}
        preview={[form.customer, form.document_ref].filter(Boolean).join(' · ')}
        testId="ai-conformity-card"
        onExpand={() => setExpanded(true)}
        onReject={readOnly ? undefined : () => reject.mutate()}
        rejectDisabled={reject.isPending}
      />
    );
  }
  return (
    <section
      aria-label={t('conformity.card.title')}
      data-testid="ai-conformity-card"
      className="flex max-w-[760px] flex-col gap-3 rounded-lg border border-ai-200 bg-ai-50 p-4"
    >
      <header className="flex items-start gap-2">
        <Sparkles size={18} aria-hidden="true" className="mt-0.5 shrink-0 text-ai-600" />
        <div className="min-w-0 flex-1">
          <h2 className="type-heading text-text-primary">{t('conformity.card.title')}</h2>
          <p className="type-small text-text-secondary">{t('conformity.card.subline')}</p>
        </div>
        <button
          type="button"
          ref={headerToggle}
          aria-expanded={true}
          onClick={() => setExpanded(false)}
          className="type-small inline-flex h-8 shrink-0 items-center gap-1 rounded-sm px-2 text-text-secondary hover:bg-bg-muted"
        >
          <ChevronUp size={16} aria-hidden="true" />
          {t('ai.card.collapsed.hide')}
        </button>
      </header>
      <dl className="type-small grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-text-primary">
        <dt className="text-text-secondary">{t('conformity.customer')}</dt>
        <dd className="whitespace-pre-line">{form.customer || '–'}</dd>
        <dt className="text-text-secondary">{t('conformity.documentRef')}</dt>
        <dd>{form.document_ref || '–'}</dd>
        <dt className="text-text-secondary">{t('conformity.card.items')}</dt>
        <dd>{form.items.length > 0 ? form.items.map((i) => i.nazov).join(', ') : t('conformity.card.noItems')}</dd>
      </dl>
      {warnings.length > 0 ? (
        <p className="type-small inline-flex items-center gap-1 text-warning-700">
          <TriangleAlert size={16} aria-hidden="true" />
          {t('conformity.card.checkNumbers')}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          icon={<FileCheck2 size={16} aria-hidden="true" />}
          disabled={readOnly}
          onClick={() => setOpen(true)}
        >
          {t('conformity.card.open')}
        </Button>
        <Button type="button" variant="secondary" disabled={reject.isPending} onClick={() => reject.mutate()}>
          {t('conformity.card.reject')}
        </Button>
      </div>
      {open ? (
        <ConformityDialog
          messageId={messageId}
          initialCustomer={form.customer}
          initialDocumentRef={form.document_ref}
          initialItems={form.items}
          suggestionId={suggestion.id}
          onIssued={done}
          onClose={() => setOpen(false)}
        />
      ) : null}
    </section>
  );
}
