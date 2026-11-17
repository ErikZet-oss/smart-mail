import { useQuery } from '@tanstack/react-query';
import { X } from 'lucide-react';
import { useEffect, useId, useRef, type KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '../../components/Button';
import { useToasts } from '../../components/toastContext';
import { authSummary, headersText } from './headersText';
import { fetchMessageHeaders } from './mailApi';

type Props = {
  mailbox: string;
  messageId: string;
  onShowSource: () => void;
  onClose: () => void;
};

const FOCUSABLE = 'button:not([disabled]),[href],[tabindex]:not([tabindex="-1"])';

/** W2p Hlavičky správy (Figma frame „W2o Hlavičky správy (dialóg)“) — all headers, read-only, Kopírovať / Zdroj. */
export function HeadersDialog({ mailbox, messageId, onShowSource, onClose }: Props) {
  const { t } = useTranslation();
  const toasts = useToasts();
  const titleId = useId();
  const ref = useRef<HTMLDivElement>(null);
  const query = useQuery({
    queryKey: ['message-headers', mailbox, messageId],
    queryFn: () => fetchMessageHeaders(mailbox, messageId),
    staleTime: Infinity,
  });

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>('[data-autofocus]')?.focus();
    return () => opener?.focus();
  }, []);

  function onKey(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== 'Tab') return;
    const items = Array.from(ref.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []);
    const first = items[0];
    const last = items[items.length - 1];
    if (!first || !last) return;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  async function copy() {
    if (!query.data) return;
    try {
      await navigator.clipboard.writeText(headersText(query.data.headers));
      toasts.success(t('mail.headers.copied'));
    } catch {
      toasts.error(t('mail.headers.copyFailed'));
    }
  }

  const auth = query.data ? authSummary(query.data.auth_results) : null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-overlay p-4">
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onKeyDown={onKey}
        data-testid="headers-dialog"
        className="flex max-h-[min(600px,100%)] w-[820px] max-w-full flex-col rounded-lg bg-bg-canvas shadow-e3"
      >
        <div className="flex h-[60px] shrink-0 items-center gap-3 border-b border-border-default px-5">
          <h2 id={titleId} className="type-heading min-w-0 flex-1 text-text-primary">
            {t('mail.headers.title')}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close')}
            className="flex size-8 shrink-0 items-center justify-center rounded-sm border border-border-strong text-text-primary hover:bg-bg-subtle focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-primary-500"
          >
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <div className="min-h-[240px] flex-1 overflow-auto px-5 py-4">
          {query.isLoading ? (
            <div aria-busy="true" className="flex flex-col gap-2">
              <div className="h-4 w-2/3 rounded-xs bg-bg-muted" />
              <div className="h-4 w-1/2 rounded-xs bg-bg-muted" />
              <div className="h-4 w-3/4 rounded-xs bg-bg-muted" />
            </div>
          ) : query.isError || !query.data ? (
            <p className="type-body text-danger-600" role="alert">
              {t('mail.headers.error')}
            </p>
          ) : (
            <dl className="font-mono text-[13px] leading-[23px] text-text-primary" data-testid="headers-list">
              {query.data.headers.map((h, i) => (
                <div key={`${h.name}-${i}`} className="whitespace-pre-wrap break-all">
                  <dt className="inline font-bold">{h.name}:</dt> <dd className="inline">{h.value}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-3 border-t border-border-default px-5 py-3">
          <p className="type-small min-w-0 basis-full text-text-secondary sm:basis-0 sm:flex-1">
            {t('mail.headers.footer')} {auth ? t('mail.headers.auth', { result: auth }) : t('mail.headers.authUnknown')}
          </p>
          <button
            type="button"
            onClick={onShowSource}
            className="type-label ml-auto rounded-xs px-2 text-brand-primary-700 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-primary-500"
          >
            {t('mail.headers.showSource')}
          </button>
          <Button variant="secondary" onClick={() => void copy()} disabled={!query.data}>
            {t('mail.headers.copy')}
          </Button>
          <Button onClick={onClose} data-autofocus>
            {t('common.close')}
          </Button>
        </div>
      </div>
    </div>
  );
}
