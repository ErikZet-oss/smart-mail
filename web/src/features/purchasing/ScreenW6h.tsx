import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  Database,
  ListChecks,
  Pencil,
  RefreshCw,
  Sigma,
  XCircle,
} from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, Navigate, useParams } from 'react-router-dom';

import { Banner } from '../../components/Banner';
import { Button } from '../../components/Button';
import { FileTypeIcon } from '../../components/FileTypeIcon';
import { fileTypeOf } from '../../components/fileType';
import { AppShell } from '../../components/shell/AppShell';
import { MOBILE_QUERY, useMediaQuery } from '../../lib/useMediaQuery';
import { fetchMe } from '../auth/authApi';
import { UPLOAD_ROLES } from '../money/docsAccess';
import { day } from '../money/moneyApi';
import { useFeaturesState } from '../system/features';
import { LineDrawer } from './LineDrawer';
import {
  addDec,
  documentKey,
  fetchDocument,
  moneyNum,
  rematch,
  type Check,
  type DocLine,
  type DocumentDetail,
} from './purchasingApi';

const VAT_ROWS = [
  ['0', 'zero'],
  ['5', 'reduced5'],
  ['19', 'reduced19'],
  ['23', 'base23'],
] as const;

const tpl = (d: DocumentDetail, key: string): string | null => {
  const v = d.template[key];
  return typeof v === 'string' && v ? v : null;
};

/**
 * W6h Dodací list prijatý – karta (Figma `43:38227`, drawer `44:37979`, M13b `85:3565` / `85:3615`).
 * A copy of the Money card „Dodací list prijatý – Karta“ (DOCUMENTS_SPEC §2). Phase 4b: matching and checks only —
 * „Vytvoriť v Money“ stays disabled until 4c; nothing is written to Money.
 */
export function ScreenW6h() {
  const { id = '' } = useParams();
  const { t } = useTranslation();
  const features = useFeaturesState();
  const mobile = useMediaQuery(MOBILE_QUERY);
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ['me'], queryFn: fetchMe, retry: false });
  const allowed = UPLOAD_ROLES.has(me.data?.person?.role ?? '');
  const doc = useQuery({
    queryKey: documentKey(id),
    queryFn: () => fetchDocument(id),
    enabled: features.money && allowed && !!id,
    retry: false,
  });
  const [panel, setPanel] = useState<'checks' | 'original' | null>(null);
  const [itemsTab, setItemsTab] = useState<'items' | 'fees'>('items');
  const [sum, setSum] = useState(true);
  const [selected, setSelected] = useState<number | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const again = useMutation({
    mutationFn: () => rematch(id),
    onSuccess: (d) => qc.setQueryData(documentKey(id), d),
  });
  if (features.loaded && !features.money) return <Navigate to="/404" replace />;
  const d = doc.data;
  const goods = d?.items.filter((l) => !l.is_fee) ?? [];
  const checks = d?.checks ?? [];
  const blocking = checks.filter((c) => c.level === 'blocking').length;
  const openLine = d && open != null ? d.items.find((l) => l.line_no === open) : undefined;

  return (
    <AppShell section="documents">
      <main className="flex min-h-0 min-w-0 flex-1 flex-col bg-bg-canvas" data-testid="screen-w6h">
        <header className="flex min-h-14 flex-wrap items-center gap-3 border-b border-border-default px-4 py-2 md:px-6">
          <Link to="/docs/delivery-notes" aria-label={t('w6h.back')} className="text-text-secondary">
            <ArrowLeft size={20} aria-hidden="true" />
          </Link>
          <h1 className="type-title text-text-primary">{t('w6h.title')}</h1>
          <span className="type-title text-text-tertiary">{t('purchasing.newDraft')}</span>
          {d ? (
            <span
              className={`type-caption inline-flex h-6 items-center rounded-full px-2 ${
                d.status === 'missing_data' ? 'bg-warning-50 text-warning-700' : 'bg-bg-muted text-text-secondary'
              }`}
              data-testid="w6h-status"
            >
              {t(`purchasing.status.${d.status}`)}
            </span>
          ) : null}
          {d?.branch_name ? (
            <span className="type-small rounded-full border border-border-default px-3 py-1 text-text-secondary">
              {t('w6h.branchChip', {
                branch: d.branch_name,
                centre: d.centre_code ?? '–',
                warehouse: d.warehouse_code ?? '–',
              })}
            </span>
          ) : null}
          {d && !mobile ? (
            <span className="type-small ml-auto truncate text-brand-primary-600">
              {t('w6h.source', { number: d.doc_number ?? d.filename })}
            </span>
          ) : null}
        </header>

        {!features.loaded || !me.data ? null : !allowed ? (
          <div className="p-6">
            <Banner kind="info" message={t('purchasing.roleOnly')} />
          </div>
        ) : doc.isLoading ? (
          <div className="flex flex-col gap-3 p-6" data-testid="w6h-loading" aria-busy="true">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="h-8 animate-pulse rounded-sm bg-bg-muted" />
            ))}
          </div>
        ) : doc.isError || !d ? (
          <div className="p-6">
            <Banner kind="warning" message={t('mail.errors.generic')} />
          </div>
        ) : (
          <>
            {!mobile ? (
              <div className="flex flex-wrap items-center gap-2 bg-bg-subtle px-4 py-2 md:px-6">
                <Button icon={<Database size={16} aria-hidden="true" />} disabled title={t('w6h.createLater')}>
                  {t('w6h.create')}
                </Button>
                <Link
                  to="/docs/delivery-notes"
                  className="type-label inline-flex h-8 items-center rounded-sm border border-border-strong bg-bg-canvas px-3"
                >
                  {t('w6h.back')}
                </Link>
                <span className="ml-auto flex gap-4">
                  <button
                    type="button"
                    className="type-label inline-flex items-center gap-2 text-brand-primary-600"
                    aria-pressed={panel === 'original'}
                    onClick={() => setPanel((p) => (p === 'original' ? null : 'original'))}
                  >
                    <FileTypeIcon type={fileTypeOf(d.filename)} />
                    {t('w6h.original')}
                  </button>
                  <button
                    type="button"
                    className="type-label inline-flex items-center gap-2 text-brand-primary-600"
                    aria-pressed={panel === 'checks'}
                    onClick={() => setPanel((p) => (p === 'checks' ? null : 'checks'))}
                    data-testid="w6h-checks-toggle"
                  >
                    <ListChecks size={16} aria-hidden="true" />
                    {t('w6h.checks', { count: checks.length })}
                  </button>
                </span>
              </div>
            ) : null}
            {!d.money_available ? (
              <div className="px-4 pt-3 md:px-6">
                <Banner kind="warning" message={t('w6h.moneyOffline')} />
              </div>
            ) : null}
            {d.status === 'duplicate' ? (
              <div className="px-4 pt-3 md:px-6">
                <Banner kind="warning" message={t('w6h.duplicate')} />
              </div>
            ) : null}
            <div className="flex min-h-0 flex-1">
              <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto pb-24 md:pb-0">
                {mobile ? (
                  <MobileCard d={d} goods={goods} onOpen={setOpen} />
                ) : (
                  <>
                    <nav className="flex gap-6 border-b border-border-default px-6" aria-label={t('w6h.title')}>
                      <span className="type-label border-b-2 border-brand-primary-600 py-3 text-brand-primary-600">
                        {t('w6h.tabs.general')}
                      </span>
                    </nav>
                    <HeaderGrid d={d} />
                    <section className="border-t border-border-default">
                      <div className="flex gap-6 px-6">
                        {(['items', 'fees'] as const).map((tab) => (
                          <button
                            key={tab}
                            type="button"
                            onClick={() => setItemsTab(tab)}
                            aria-pressed={itemsTab === tab}
                            className={`type-label inline-flex items-center gap-2 py-3 ${
                              itemsTab === tab
                                ? 'border-b-2 border-brand-primary-600 text-brand-primary-600'
                                : 'text-text-secondary'
                            }`}
                          >
                            {t(`w6h.itemTabs.${tab}`)}
                            <span className="type-caption rounded-full bg-bg-muted px-1.5">
                              {tab === 'items' ? goods.length : d.items.length - goods.length}
                            </span>
                          </button>
                        ))}
                      </div>
                      {itemsTab === 'items' ? (
                        <>
                          <div className="flex flex-wrap items-center gap-4 bg-bg-subtle px-4 py-2">
                            <ToolButton
                              icon={<Pencil size={14} aria-hidden="true" />}
                              disabled={selected == null}
                              onClick={() => setOpen(selected)}
                            >
                              {t('w6h.tool.edit')}
                            </ToolButton>
                            <ToolButton
                              icon={<RefreshCw size={14} aria-hidden="true" />}
                              disabled={again.isPending}
                              onClick={() => again.mutate()}
                            >
                              {t('w6h.tool.rematch')}
                            </ToolButton>
                            <ToolButton icon={<Sigma size={14} aria-hidden="true" />} onClick={() => setSum((s) => !s)}>
                              Σ
                            </ToolButton>
                          </div>
                          <ItemsGrid
                            lines={goods}
                            sum={sum}
                            selected={selected}
                            onSelect={setSelected}
                            onOpen={setOpen}
                          />
                        </>
                      ) : (
                        <Fees d={d} />
                      )}
                    </section>
                  </>
                )}
              </div>
              {panel && !mobile ? (
                <aside
                  className="flex w-[420px] shrink-0 flex-col overflow-y-auto border-l border-border-default"
                  data-testid={`w6h-panel-${panel}`}
                >
                  {panel === 'checks' ? (
                    <ChecksList checks={checks} />
                  ) : (
                    <iframe
                      title={t('w6h.original')}
                      src={`/api/purchasing/documents/${d.id}/file`}
                      className="h-full w-full"
                    />
                  )}
                </aside>
              ) : null}
            </div>
            {mobile ? (
              <div className="fixed inset-x-0 bottom-0 z-20 flex flex-col gap-2 border-t border-border-default bg-bg-canvas p-3 pb-[calc(env(safe-area-inset-bottom)+12px)]">
                <span className="type-caption text-danger-600" data-testid="m13b-summary">
                  {t('w6h.mobileSummary', {
                    blocking: goods.filter((l) => l.line_status === 'unmatched').length,
                    warnings: checks.filter((c) => c.level === 'warning').length,
                  })}
                </span>
                <Button size="lg" disabled title={t('w6h.createLater')}>
                  {t('w6h.create')}
                </Button>
              </div>
            ) : null}
            {openLine ? (
              <LineDrawer
                doc={d}
                line={openLine}
                sheet={mobile}
                onClose={() => setOpen(null)}
                onSaved={(next) => {
                  qc.setQueryData(documentKey(id), next);
                  setOpen(null);
                }}
              />
            ) : null}
            <span className="sr-only" aria-live="polite">
              {blocking ? t('w6h.blockingCount', { count: blocking }) : ''}
            </span>
          </>
        )}
      </main>
    </AppShell>
  );
}

function ToolButton({
  icon,
  children,
  onClick,
  disabled,
}: {
  icon: ReactNode;
  children: ReactNode;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="type-small inline-flex items-center gap-1.5 text-text-primary disabled:text-text-tertiary"
    >
      {icon}
      {children}
    </button>
  );
}

function Field({ label, value, bold, wide }: { label: string; value: ReactNode; bold?: boolean; wide?: boolean }) {
  return (
    <div className={`flex items-center gap-2 ${wide ? 'col-span-2' : ''}`}>
      <span className={`type-small w-32 shrink-0 text-right text-text-primary ${bold ? 'font-semibold' : ''}`}>
        {label}
      </span>
      <span
        className={`type-small flex h-8 min-w-0 items-center overflow-hidden whitespace-nowrap rounded-sm border border-border-default bg-bg-muted px-2 text-text-secondary ${
          wide ? 'flex-1' : 'w-[150px] shrink-0'
        }`}
      >
        {value}
      </span>
    </div>
  );
}

function Group({ title }: { title: string }) {
  return (
    <div className="col-span-1 flex items-center gap-2 pt-2">
      <span className="type-label text-brand-primary-600">{title}</span>
      <span className="h-px flex-1 bg-border-default" />
    </div>
  );
}

function HeaderGrid({ d }: { d: DocumentDetail }) {
  const { t } = useTranslation();
  const first = d.items.find((l) => !l.is_fee);
  const L = (k: string) => t(`w6h.f.${k}`);
  const onWrite = t('w6h.onWrite');
  const goodsTotal = d.items
    .filter((l) => !l.is_fee)
    .reduce((acc, l) => (l.line_total ? addDec(acc, l.line_total) : acc), '0');
  return (
    <div className="grid grid-cols-1 gap-6 p-6 xl:grid-cols-[minmax(0,560px)_minmax(0,1fr)]">
      <div className="grid grid-cols-2 gap-x-6 gap-y-2" data-testid="w6h-header">
        <div className="col-span-2 flex items-center gap-2">
          <span className="type-small w-32 shrink-0 text-right">{L('number')}</span>
          <span className="type-small flex h-8 w-[100px] items-center whitespace-nowrap rounded-sm border border-border-default bg-bg-muted px-2 text-text-tertiary">
            {t('w6h.assigned')}
          </span>
          <span className="type-label flex h-8 items-center rounded-sm border border-border-default px-2">
            {d.series ?? '—'}
          </span>
        </div>
        <Field label={L('description')} value={first?.article?.name ?? first?.name ?? '–'} wide />
        <Field label={L('received')} value={d.delivery_note_number ?? d.doc_number ?? '–'} />
        <Field label={L('pairing')} value={d.kind === 'invoice' ? (d.doc_number ?? '') : ''} />
        <Field label={L('return')} value={<input type="checkbox" disabled aria-label={L('return')} />} />
        <span />
        <Field label={L('vatReg')} value={tpl(d, 'registration') ?? '—'} />
        <Field label={L('payment')} value="" />
        <Field label={L('preAccount')} value={tpl(d, 'predkontace') ?? '—'} bold />
        <Field label={L('movement')} value={tpl(d, 'druh_pohybu') ?? '—'} />
        <span />
        <Field label={L('stockMovement')} value={tpl(d, 'druh_skladoveho_pohybu') ?? '—'} />
        <Group title={L('date')} />
        <Group title={L('details')} />
        <Field label={L('issued')} value={day(d.doc_date)} />
        <Field label={L('centre')} value={d.centre_code ? `${d.centre_code} – ${d.branch_name ?? ''}` : '—'} />
        <Field label={L('accounting')} value={onWrite} />
        <Field label={L('discount')} value="0,00" />
        <Field label={L('movedAt')} value={t('w6h.onWriteMoney')} />
        <Field label={L('totalCost')} value={moneyNum(goodsTotal, 2)} />
      </div>
      <div className="flex min-w-0 flex-col gap-3">
        <span className="type-label w-fit border-b-2 border-brand-primary-600 pb-2 text-brand-primary-600">
          {t('w6h.supplierTab')}
        </span>
        {d.supplier ? (
          <div className="flex max-w-[490px] flex-col gap-2" data-testid="w6h-supplier">
            <Field label={L('ico')} value={d.supplier.ico ?? '–'} />
            <Field label={L('dic')} value={d.supplier.dic ?? '–'} />
            <Field label={L('icdph')} value={d.supplier.icdph ?? '–'} />
            <Field label={L('company')} value={d.supplier.name} wide />
          </div>
        ) : (
          <Banner kind="warning" message={t('w6h.supplierMissing')} />
        )}
        <table className="type-small w-full max-w-[490px] border border-border-default" data-testid="w6h-vat">
          <thead className="bg-bg-subtle text-text-secondary">
            <tr>
              <th className="px-2 py-1 text-left font-normal">{L('rate')}</th>
              <th className="px-2 py-1 text-right font-normal">{L('base')}</th>
              <th className="px-2 py-1 text-right font-normal">{L('vat')}</th>
              <th className="px-2 py-1 text-right font-normal">{L('withVat')}</th>
            </tr>
          </thead>
          <tbody>
            {VAT_ROWS.map(([rate, key]) => {
              const row = d.vat_recap.find((r) => Number(r.rate) === Number(rate));
              const base = row?.base ?? '0';
              const vat = row?.vat ?? '0';
              return (
                <tr key={rate}>
                  <td className="px-2 py-1">{t(`w6h.vatRows.${key}`)}</td>
                  <td className="px-2 py-1 text-right tabular-nums">{moneyNum(base, 2)}</td>
                  <td className="px-2 py-1 text-right tabular-nums">{moneyNum(vat, 2)}</td>
                  <td className="px-2 py-1 text-right tabular-nums">{moneyNum(addDec(base, vat), 2)}</td>
                </tr>
              );
            })}
            <tr className="border-t border-border-default">
              <td className="px-2 py-1">{d.currency ?? 'EUR'}</td>
              <td colSpan={3} className="px-2 py-1 text-right">
                {L('total')} <strong className="tabular-nums">{d.total ? moneyNum(d.total, 2) : '–'}</strong>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

function StatusIcon({ line }: { line: DocLine }) {
  const { t } = useTranslation();
  if (line.line_status === 'unmatched')
    return <XCircle size={16} className="text-danger-600" aria-label={t('w6h.lineStatus.unmatched')} />;
  if (line.line_status === 'non_stock')
    return (
      <span className="type-caption font-semibold text-text-secondary" aria-label={t('w6h.lineStatus.non_stock')}>
        T
      </span>
    );
  if (line.match_method === 'learned' || line.match_method === 'ean' || line.match_method === 'our_code')
    return <AlertCircle size={16} className="text-warning-600" aria-label={t('w6h.lineStatus.check')} />;
  return <CheckCircle2 size={16} className="text-success-600" aria-label={t('w6h.lineStatus.matched')} />;
}

const COLS = [
  'order',
  'name',
  'catalog',
  'supplierCode',
  'warehouse',
  'qty',
  'unit',
  'vat',
  'priceType',
  'price',
  'total',
  'ean',
  'kind',
] as const;

function ItemsGrid({
  lines,
  sum,
  selected,
  onSelect,
  onOpen,
}: {
  lines: DocLine[];
  sum: boolean;
  selected: number | null;
  onSelect: (n: number) => void;
  onOpen: (n: number) => void;
}) {
  const { t } = useTranslation();
  const total = lines.reduce((acc, l) => (l.line_total ? addDec(acc, l.line_total) : acc), '0');
  const right = new Set(['qty', 'price', 'total', 'vat', 'order']);
  return (
    <div className="overflow-x-auto">
      <table
        className="type-small w-full min-w-[1280px] whitespace-nowrap text-left text-text-primary"
        data-testid="w6h-grid"
      >
        <thead className="sticky top-0 bg-bg-subtle text-text-secondary">
          <tr>
            <th className="w-8 px-2 py-1">
              <span className="sr-only">{t('w6h.cols.status')}</span>
            </th>
            {COLS.map((c) => (
              <th key={c} className={`px-2 py-1 font-normal ${right.has(c) ? 'text-right' : ''}`}>
                {t(`w6h.cols.${c}`)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {lines.map((l) => {
            const tone =
              l.line_status === 'unmatched'
                ? 'bg-danger-50 text-danger-600'
                : l.match_method === 'learned' || l.match_method === 'ean' || l.match_method === 'our_code'
                  ? 'bg-warning-50'
                  : '';
            return (
              <tr
                key={l.line_no}
                data-testid={`w6h-line-${l.line_no}`}
                tabIndex={0}
                aria-selected={selected === l.line_no}
                onClick={() => onSelect(l.line_no)}
                onDoubleClick={() => onOpen(l.line_no)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') onOpen(l.line_no);
                }}
                className={`h-6 cursor-pointer select-none border-t border-border-default ${tone} ${
                  selected === l.line_no ? 'outline outline-2 -outline-offset-2 outline-brand-primary-500' : ''
                }`}
              >
                <td className="px-2">
                  <StatusIcon line={l} />
                </td>
                <td className="px-2 text-right tabular-nums">{l.line_no}</td>
                <td className="max-w-[220px] truncate px-2">{l.article?.name ?? `${l.name}`}</td>
                <td className="px-2">{l.article?.catalog ?? l.article?.code ?? '—'}</td>
                <td className="px-2">{l.supplier_code ?? '—'}</td>
                <td className="px-2">{l.warehouse_code ?? '—'}</td>
                <td className="px-2 text-right tabular-nums">{moneyNum(l.qty_our ?? l.qty, 4)}</td>
                <td className="px-2">{l.article?.unit ?? l.unit ?? '—'}</td>
                <td className="px-2 text-right tabular-nums">{l.vat_rate ? `${moneyNum(l.vat_rate, 0)} %` : '—'}</td>
                <td className="px-2">{t('w6h.priceTypeBase')}</td>
                <td className="px-2 text-right tabular-nums">{moneyNum(l.price_our ?? l.unit_price, 4)}</td>
                <td className="px-2 text-right tabular-nums">{moneyNum(l.line_total, 2)}</td>
                <td className="max-w-[140px] truncate px-2">{l.article?.ean ?? '—'}</td>
                <td className="px-2">{l.line_status === 'non_stock' ? t('w6h.nonStock') : t('w6h.goods')}</td>
              </tr>
            );
          })}
        </tbody>
        {sum ? (
          <tfoot>
            <tr className="border-t border-border-strong bg-bg-subtle">
              <td />
              <td colSpan={2} className="px-2 py-1">
                Σ {t('purchasing.linesCount', { count: lines.length })}
              </td>
              <td colSpan={8} />
              <td className="px-2 py-1 text-right font-semibold tabular-nums" data-testid="w6h-sum">
                {moneyNum(total, 2)}
              </td>
              <td colSpan={2} />
            </tr>
          </tfoot>
        ) : null}
      </table>
    </div>
  );
}

function Fees({ d }: { d: DocumentDetail }) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-3 p-6" data-testid="w6h-fees">
      <Banner kind="info" message={t('w6h.feesInfo')} />
      <ul className="type-small flex flex-col divide-y divide-border-default rounded-md border border-border-default">
        {d.fees.map((f, i) => (
          <li key={i} className="flex justify-between px-3 py-2">
            <span>{f.name}</span>
            <span className="tabular-nums">{moneyNum(f.amount, 2)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ChecksList({ checks }: { checks: Check[] }) {
  const { t } = useTranslation();
  if (!checks.length) return <p className="type-body p-4 text-text-secondary">{t('w6h.noChecks')}</p>;
  return (
    <ul className="flex flex-col divide-y divide-border-default">
      {checks.map((c, i) => (
        <li key={i} className="flex gap-2 p-4" data-testid={`check-${c.id}`}>
          {c.level === 'blocking' ? (
            <XCircle size={16} className="mt-0.5 shrink-0 text-danger-600" aria-hidden="true" />
          ) : (
            <AlertCircle size={16} className="mt-0.5 shrink-0 text-warning-600" aria-hidden="true" />
          )}
          <span className="type-small text-text-primary">
            <strong className="mr-1">{c.id}</strong>
            {t(`w6h.rules.${c.id}`, { ...c.params, defaultValue: '' })}
          </span>
        </li>
      ))}
    </ul>
  );
}

function MobileGroup({ title, rows }: { title: string; rows: [string, ReactNode][] }) {
  return (
    <section className="overflow-hidden rounded-md border border-border-default">
      <h2 className="type-label bg-brand-primary-50 px-3 py-2 text-brand-primary-700">{title}</h2>
      <dl className="divide-y divide-border-default">
        {rows.map(([k, v]) => (
          <div key={k} className="type-small flex gap-2 px-3 py-2">
            <dt className="w-32 shrink-0 text-text-secondary">{k}</dt>
            <dd className="min-w-0 break-words text-text-primary">{v}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function MobileCard({ d, goods, onOpen }: { d: DocumentDetail; goods: DocLine[]; onOpen: (n: number) => void }) {
  const { t } = useTranslation();
  const L = (k: string) => t(`w6h.f.${k}`);
  const vat = d.vat_recap[0];
  return (
    <div className="flex flex-col gap-3 p-4" data-testid="m13b">
      <MobileGroup
        title={t('w6h.groups.header')}
        rows={[
          [L('number'), t('w6h.assigned')],
          [L('received'), d.delivery_note_number ?? d.doc_number ?? '–'],
          [L('pairing'), d.kind === 'invoice' ? (d.doc_number ?? '–') : '–'],
          [L('preAccount'), tpl(d, 'predkontace') ?? '—'],
        ]}
      />
      <MobileGroup
        title={t('w6h.supplierTab')}
        rows={[
          [L('company'), d.supplier?.name ?? d.supplier_name ?? '–'],
          [`${L('ico')} · ${L('dic')}`, `${d.supplier?.ico ?? d.supplier_ico ?? '–'} · ${d.supplier?.dic ?? '–'}`],
        ]}
      />
      <MobileGroup
        title={L('date')}
        rows={[
          [L('issued'), day(d.doc_date)],
          [L('movedAt'), t('w6h.onWriteMoney')],
        ]}
      />
      <MobileGroup
        title={L('details')}
        rows={[
          [L('centre'), d.centre_code ? `${d.centre_code} – ${d.branch_name ?? ''}` : '—'],
          [L('movement'), tpl(d, 'druh_pohybu') ?? '—'],
        ]}
      />
      {vat ? (
        <MobileGroup
          title={t('w6h.groups.vat')}
          rows={[[`${moneyNum(vat.rate, 0)} %`, `${moneyNum(vat.base, 2)} · ${L('vat')} ${moneyNum(vat.vat, 2)}`]]}
        />
      ) : null}
      <h2 className="type-heading text-text-primary">
        {t('w6h.itemTabs.items')} ({goods.length})
      </h2>
      <ul className="flex flex-col gap-2">
        {goods.map((l) => (
          <li key={l.line_no}>
            <button
              type="button"
              onClick={() => onOpen(l.line_no)}
              data-testid={`m13b-line-${l.line_no}`}
              className={`type-small flex w-full flex-col gap-1 rounded-md border p-3 text-left ${
                l.line_status === 'unmatched'
                  ? 'border-danger-200 bg-danger-50'
                  : l.match_method === 'learned' || l.match_method === 'ean' || l.match_method === 'our_code'
                    ? 'border-warning-200 bg-warning-50'
                    : 'border-border-default'
              }`}
            >
              <span className="type-label flex items-center gap-2">
                <StatusIcon line={l} />
                {l.line_no}. {l.article?.name ?? l.name}
              </span>
              <span className="text-text-secondary">
                {L('catalogShort')} {l.article?.catalog ?? l.article?.code ?? '—'} · {L('supplierCodeShort')}{' '}
                {l.supplier_code ?? '—'}
              </span>
              <span className="flex justify-between tabular-nums">
                <span>
                  {moneyNum(l.qty_our ?? l.qty, 4)} {l.article?.unit ?? l.unit ?? ''}
                </span>
                <span>
                  {moneyNum(l.price_our ?? l.unit_price, 4)} €/{l.article?.unit ?? l.unit ?? ''}{' '}
                  <strong>{moneyNum(l.line_total, 2)} €</strong>
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
