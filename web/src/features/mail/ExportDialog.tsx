import { useMutation, useQuery } from '@tanstack/react-query';
import { Download } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '../../components/Button';
import { Dialog } from '../../components/Dialog';
import { ApiError } from '../../lib/api';
import {
  estimateExport,
  exportDownloadUrl,
  fetchExport,
  startExport,
  type ExportRange,
  type ExportRequest,
} from './mailApi';

const INPUT =
  'type-body rounded-md border border-border-default bg-bg-surface px-2 py-1 text-text-primary focus:outline-none focus:ring-2 focus:ring-brand-primary-500';

function formatSize(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1).replace('.', ',')} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1).replace('.', ',')} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} kB`;
}

type Props = {
  mailboxRef: string;
  /** null = the whole mailbox */
  folder: { id: string; label: string; hasChildren: boolean } | null;
  onClose: () => void;
};

/** #127 „Stiahnuť priečinok (.zip)…“ / „Stiahnuť celú schránku (.zip)…“: range → estimate → background job →
 * progress → download (24 h). No Figma frame exists — built from the Dialog component (noted in the PR). */
export function ExportDialog({ mailboxRef, folder, onClose }: Props) {
  const { t } = useTranslation();
  const [kind, setKind] = useState<ExportRange['kind']>('all');
  const [months, setMonths] = useState(12);
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [children, setChildren] = useState(true);
  const [exportId, setExportId] = useState<string | null>(null);

  const range: ExportRange =
    kind === 'older'
      ? { kind, months }
      : kind === 'between'
        ? { kind, date_from: dateFrom || null, date_to: dateTo || null }
        : { kind };
  const rangeValid = kind !== 'between' || (dateFrom !== '' && dateTo !== '' && dateFrom <= dateTo);
  const request: ExportRequest = {
    folder_ids: folder ? [folder.id] : null,
    include_children: folder ? folder.hasChildren && children : false,
    range,
  };

  const estimate = useQuery({
    queryKey: ['mail', 'export-estimate', mailboxRef, request],
    queryFn: () => estimateExport(mailboxRef, request),
    enabled: rangeValid && exportId === null,
  });
  const start = useMutation({
    mutationFn: () => startExport(mailboxRef, request),
    onSuccess: (state) => setExportId(state.id),
  });
  const status = useQuery({
    queryKey: ['mail', 'export', exportId],
    queryFn: () => fetchExport(exportId ?? ''),
    enabled: exportId !== null,
    refetchInterval: (query) => {
      const s = query.state.data?.status;
      return s === 'ready' || s === 'failed' ? false : 1500;
    },
  });

  const title = folder ? t('mailExport.titleFolder', { name: folder.label }) : t('mailExport.titleMailbox');
  const state = status.data;
  const startError = start.error instanceof ApiError ? start.error.detail.code : null;

  if (exportId !== null) {
    const pct = state && state.total > 0 ? Math.round((100 * state.done) / state.total) : 0;
    return (
      <Dialog
        title={title}
        width={460}
        onClose={onClose}
        footer={
          <Button type="button" variant="secondary" onClick={onClose}>
            {t('mailExport.close')}
          </Button>
        }
      >
        <div className="flex flex-col gap-3" data-testid="export-progress">
          {state?.status === 'ready' ? (
            <>
              <p className="type-body text-text-primary">
                {t('mailExport.ready', { count: state.done, size: formatSize(state.archive_size) })}
              </p>
              <a
                href={exportDownloadUrl(state.id)}
                download={state.filename}
                className="type-label inline-flex items-center gap-1 self-start rounded-md bg-brand-primary-600 px-3 py-2 text-white hover:bg-brand-primary-700"
              >
                <Download size={16} aria-hidden="true" />
                {t('mailExport.download')}
              </a>
              <p className="type-small text-text-secondary">{t('mailExport.validFor')}</p>
            </>
          ) : state?.status === 'failed' ? (
            <p role="alert" className="type-body text-danger-600">
              {t('mailExport.failed')}
            </p>
          ) : (
            <>
              <p className="type-body text-text-primary">
                {state && state.total > 0
                  ? t('mailExport.progress', { done: state.done, total: state.total })
                  : t('mailExport.preparing')}
              </p>
              <div
                role="progressbar"
                aria-label={t('mailExport.progressLabel')}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={pct}
                className="h-2 w-full overflow-hidden rounded-full bg-bg-subtle"
              >
                <div className="h-full bg-brand-primary-600 transition-all" style={{ width: `${pct}%` }} />
              </div>
              <p className="type-small text-text-secondary">{t('mailExport.background')}</p>
            </>
          )}
        </div>
      </Dialog>
    );
  }

  return (
    <Dialog
      title={title}
      width={460}
      onClose={onClose}
      onSubmit={() => {
        if (rangeValid && !start.isPending) start.mutate();
      }}
      footer={
        <>
          <Button type="button" variant="secondary" onClick={onClose}>
            {t('mailExport.cancel')}
          </Button>
          <Button type="submit" disabled={!rangeValid || start.isPending || estimate.data?.messages === 0}>
            {t('mailExport.start')}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3" data-testid="export-dialog">
        <fieldset className="flex flex-col gap-2">
          <legend className="type-label mb-1 text-text-secondary">{t('mailExport.range')}</legend>
          <label className="type-body inline-flex items-center gap-2 text-text-primary">
            <input type="radio" name="export-range" checked={kind === 'all'} onChange={() => setKind('all')} />
            {t('mailExport.all')}
          </label>
          <label className="type-body inline-flex flex-wrap items-center gap-2 text-text-primary">
            <input type="radio" name="export-range" checked={kind === 'older'} onChange={() => setKind('older')} />
            {t('mailExport.olderThan')}
            <input
              type="number"
              min={1}
              max={240}
              className={`${INPUT} w-20`}
              aria-label={t('mailExport.months')}
              value={months}
              onChange={(e) => {
                setKind('older');
                setMonths(Math.min(240, Math.max(1, Number(e.target.value) || 1)));
              }}
            />
            {t('mailExport.monthsUnit')}
          </label>
          <label className="type-body inline-flex flex-wrap items-center gap-2 text-text-primary">
            <input type="radio" name="export-range" checked={kind === 'between'} onChange={() => setKind('between')} />
            {t('mailExport.between')}
            <input
              type="date"
              className={INPUT}
              aria-label={t('mailExport.from')}
              value={dateFrom}
              onChange={(e) => {
                setKind('between');
                setDateFrom(e.target.value);
              }}
            />
            –
            <input
              type="date"
              className={INPUT}
              aria-label={t('mailExport.to')}
              value={dateTo}
              onChange={(e) => {
                setKind('between');
                setDateTo(e.target.value);
              }}
            />
          </label>
        </fieldset>
        {folder?.hasChildren ? (
          <label className="type-body inline-flex items-center gap-2 text-text-primary">
            <input type="checkbox" checked={children} onChange={(e) => setChildren(e.target.checked)} />
            {t('mailExport.children')}
          </label>
        ) : null}
        <p className="type-small text-text-secondary" data-testid="export-estimate" aria-live="polite">
          {!rangeValid
            ? t('mailExport.pickDates')
            : estimate.data
              ? t('mailExport.estimate', { count: estimate.data.messages, size: formatSize(estimate.data.bytes) })
              : t('mailExport.estimating')}
        </p>
        <p className="type-small text-text-secondary">{t('mailExport.format')}</p>
        {startError ? (
          <p role="alert" className="type-small text-danger-600">
            {t(`mailExport.errors.${startError}`, { defaultValue: t('mailExport.errors.generic') })}
          </p>
        ) : null}
      </div>
    </Dialog>
  );
}
