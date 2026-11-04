import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle2, Package, XCircle } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { Button } from '../../components/Button';
import { ConfirmDialog } from '../../components/Dialog';
import { FileTypeIcon } from '../../components/FileTypeIcon';
import { fileTypeOf } from '../../components/fileType';
import { useToasts } from '../../components/toastContext';
import { api } from '../../lib/api';
import { money } from '../money/moneyApi';
import { moneyNum } from './purchasingApi';

/** #208 — one supplier document read from this message (`GET …/messages/{id}/documents`). */
export type ThreadDocCard = {
  id: string;
  status: string;
  kind: string;
  filename: string;
  attachment_id: string | null;
  supplier_name: string | null;
  supplier_ico: string | null;
  supplier_in_money: boolean | null;
  doc_number: string | null;
  currency: string | null;
  total: string | null;
  lines: number;
  matched: number;
  to_confirm: number;
  unmatched: number;
  matching_done: boolean;
  confidence: number | null;
  checks: { id: string; level: string; params: Record<string, unknown> }[];
  money_number: string | null;
  error: string | null;
  money_available: boolean;
};

const threadDocsKey = (mailbox: string, messageId: string) =>
  ['purchasing', 'thread-docs', mailbox, messageId] as const;

/**
 * „Príjem tovaru“ cards in W2c / M3 (Figma `22:6603`, #208): what Smart Mail read from the supplier's invoice or
 * delivery note in this message. Read-only — „Pripraviť dodací list“ only opens W6h; nothing is written to Money.
 */
export function GoodsReceiptCards({ mailbox, messageId }: { mailbox: string; messageId: string }) {
  const docs = useQuery({
    queryKey: threadDocsKey(mailbox, messageId),
    queryFn: () =>
      api<ThreadDocCard[]>('GET', `/api/purchasing/mailboxes/${mailbox}/messages/${messageId}/documents`, undefined, {
        global: false,
      }),
    retry: false,
    // the intake worker reads the PDF in the background — refresh until it is done
    refetchInterval: (q) => ((q.state.data ?? []).some((d) => d.status === 'extracting') ? 4000 : false),
  });
  const list = docs.data ?? [];
  if (!list.length) return null;
  return (
    <div className="flex flex-col gap-2 pb-3" data-testid="goods-receipt-cards">
      {list.map((d) => (
        <GoodsReceiptCard key={d.id} doc={d} mailbox={mailbox} messageId={messageId} />
      ))}
    </div>
  );
}

function CheckRow({ ok, warn, text }: { ok: boolean; warn?: boolean; text: string }) {
  return (
    <li className="type-small flex items-center gap-2 text-text-primary">
      {ok ? (
        <CheckCircle2 size={16} aria-hidden="true" className="shrink-0 text-success-600" />
      ) : warn ? (
        <AlertTriangle size={16} aria-hidden="true" className="shrink-0 text-warning-600" />
      ) : (
        <XCircle size={16} aria-hidden="true" className="shrink-0 text-danger-600" />
      )}
      {text}
    </li>
  );
}

function GoodsReceiptCard({ doc, mailbox, messageId }: { doc: ThreadDocCard; mailbox: string; messageId: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const toasts = useToasts();
  const qc = useQueryClient();
  const [confirm, setConfirm] = useState(false);
  const reject = useMutation({
    mutationFn: () => api('POST', `/api/purchasing/documents/${doc.id}/ignore`, {}, { global: false }),
    onSuccess: () => {
      setConfirm(false);
      void qc.invalidateQueries({ queryKey: threadDocsKey(mailbox, messageId) });
      toasts.success(t('goods.rejected'));
    },
    onError: () => toasts.error(t('mail.errors.generic')),
  });
  const L = (k: string, o?: Record<string, unknown>) => t(`goods.${k}`, o);
  const reading = doc.status === 'extracting';
  const failed = doc.status === 'unreadable' || doc.status === 'failed';
  const sumBad = doc.checks.some((c) => c.id === 'DL-B7');
  const total = doc.lines || 1;
  const pct = (n: number) => `${(n / total) * 100}%`;
  const subline = [
    doc.supplier_name,
    doc.doc_number ? `${doc.kind === 'delivery_note' ? 'DL' : 'FA'} ${doc.doc_number}` : null,
    doc.lines ? t('purchasing.linesCount', { count: doc.lines }) : null,
  ]
    .filter(Boolean)
    .join(' · ');

  return (
    <section
      aria-label={L('title')}
      data-testid="goods-receipt-card"
      className="flex max-w-[760px] flex-col gap-3 rounded-lg border border-ai-200 bg-ai-50 p-4"
    >
      <header className="flex items-start gap-3">
        <span className="inline-flex size-9 shrink-0 items-center justify-center rounded-md border border-ai-200 bg-bg-canvas text-ai-600">
          <Package size={18} aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="type-micro uppercase tracking-wide text-ai-600">{L('label')}</p>
          <h2 className="type-heading text-text-primary">{L('title')}</h2>
        </div>
        {doc.confidence !== null && !reading ? (
          <span className="type-caption shrink-0 text-success-600">
            {L('confidence', { value: doc.confidence.toFixed(2).replace('.', ',') })}
          </span>
        ) : null}
      </header>

      {reading ? (
        <div aria-busy="true" className="flex flex-col gap-2" data-testid="goods-reading">
          <p className="type-small text-text-secondary">{L('reading')}</p>
          <div className="h-3 w-2/3 animate-pulse rounded-sm bg-bg-muted" />
          <div className="h-3 w-1/2 animate-pulse rounded-sm bg-bg-muted" />
        </div>
      ) : failed ? (
        <p className="type-small text-danger-600" data-testid="goods-failed">
          {L('failed')}
        </p>
      ) : (
        <>
          {subline ? <p className="type-small text-text-secondary">{subline}</p> : null}
          <ul className="flex flex-col gap-1.5">
            {doc.supplier_in_money === null ? (
              <CheckRow ok={false} warn text={L('moneyOffline')} />
            ) : (
              <CheckRow
                ok={doc.supplier_in_money}
                text={
                  doc.supplier_in_money
                    ? L('supplierOk', { ico: doc.supplier_ico ?? '–' })
                    : L('supplierMissing', { ico: doc.supplier_ico ?? '–' })
                }
              />
            )}
            {doc.matching_done ? (
              <CheckRow
                ok={doc.to_confirm === 0 && doc.unmatched === 0}
                warn={doc.unmatched === 0}
                text={L('matched', {
                  done: doc.matched,
                  total: doc.lines,
                  rest: doc.to_confirm + doc.unmatched,
                })}
              />
            ) : null}
            {doc.total ? (
              <CheckRow
                ok={!sumBad}
                text={
                  sumBad
                    ? L('sumBad')
                    : L('sumOk', {
                        total:
                          doc.currency && doc.currency !== 'EUR'
                            ? `${moneyNum(doc.total, 2)} ${doc.currency}`
                            : money(doc.total),
                      })
                }
              />
            ) : null}
          </ul>
          {doc.matching_done ? (
            <>
              <div
                className="flex h-1.5 overflow-hidden rounded-full bg-bg-muted"
                role="img"
                aria-label={L('legend', { matched: doc.matched, confirm: doc.to_confirm, unmatched: doc.unmatched })}
                data-testid="goods-progress"
              >
                <span className="bg-success-600" style={{ width: pct(doc.matched) }} />
                <span className="bg-warning-600" style={{ width: pct(doc.to_confirm) }} />
              </div>
              <div className="type-caption flex flex-wrap items-center gap-x-4 gap-y-2">
                <span className="text-success-600">{L('legendMatched', { count: doc.matched })}</span>
                <span className="text-warning-700">{L('legendConfirm', { count: doc.to_confirm })}</span>
                <span className="text-text-secondary">{L('legendUnmatched', { count: doc.unmatched })}</span>
                <span className="type-small ml-auto inline-flex items-center gap-1.5 rounded-sm border border-border-default bg-bg-canvas px-2.5 py-1 text-text-primary">
                  <FileTypeIcon type={fileTypeOf(doc.filename)} />
                  {doc.filename}
                </span>
              </div>
            </>
          ) : null}
        </>
      )}

      {doc.money_number ? (
        <p className="type-small text-text-primary">{L('inMoney', { number: doc.money_number })}</p>
      ) : (
        <div className="flex flex-wrap items-center gap-3">
          <Button
            onClick={() => navigate(`/docs/delivery-notes/${doc.id}`)}
            data-testid="goods-open"
            disabled={reading}
          >
            {failed ? L('openDoc') : L('prepare')}
          </Button>
          <button
            type="button"
            className="type-label h-8 px-2 text-brand-primary-700"
            onClick={() => setConfirm(true)}
            data-testid="goods-reject"
          >
            {L('reject')}
          </button>
        </div>
      )}
      <p className="type-caption text-text-secondary">{t('ai.card.footer')}</p>
      {confirm ? (
        <ConfirmDialog
          title={L('rejectTitle')}
          body={L('rejectText')}
          confirmLabel={L('reject')}
          busy={reject.isPending}
          onConfirm={() => reject.mutate()}
          onClose={() => setConfirm(false)}
        />
      ) : null}
    </section>
  );
}
