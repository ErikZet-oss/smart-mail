import { Database, Info } from 'lucide-react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '../../components/Button';
import { Dialog } from '../../components/Dialog';
import { addDec, moneyNum, type DocumentDetail } from './purchasingApi';

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center gap-2">
      <span className="type-small w-[140px] shrink-0 text-text-secondary">{label}</span>
      <span className="type-body min-w-0 flex-1 break-words text-text-primary">{children}</span>
    </div>
  );
}

/**
 * W6h confirm dialog „Zapísať dodací list do Money ako koncept?“ (D33, Figma `44:39649` in frame `44:38842`): the
 * summary the person approves — supplier, numbers, lines, warehouse, centre · series, total, stock movement time.
 */
export function WriteDialog({
  d,
  busy,
  onConfirm,
  onClose,
}: {
  d: DocumentDetail;
  busy: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const goods = d.items.filter((l) => !l.is_fee);
  const total = goods.reduce((acc, l) => (l.line_total ? addDec(acc, l.line_total) : acc), '0');
  const fees = d.items
    .filter((l) => l.is_fee)
    .reduce((acc, l) => (l.line_total ? addDec(acc, l.line_total) : acc), '0');
  const nonStock = goods.filter((l) => l.line_status === 'non_stock').length;
  const warehouse = d.warehouses.find((w) => w.code === d.warehouse_code);
  const odkaz = d.kind === 'invoice' ? (d.delivery_note_number ?? d.doc_number) : d.doc_number;
  const pairing = d.kind === 'invoice' ? d.doc_number : null;
  return (
    <Dialog
      title={t('w6h.write.title')}
      width={520}
      onClose={onClose}
      onSubmit={onConfirm}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} data-autofocus>
            {t('common.cancel')}
          </Button>
          <Button
            type="submit"
            icon={<Database size={16} aria-hidden="true" />}
            disabled={busy}
            data-testid="w6h-write-confirm"
          >
            {t('w6h.write.confirm')}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4" data-testid="w6h-write-dialog">
        <Row label={t('w6h.write.supplier')}>
          {t('w6h.write.supplierValue', {
            name: d.supplier?.name ?? d.supplier_name ?? '–',
            ico: d.supplier?.ico ?? d.supplier_ico ?? '–',
          })}
        </Row>
        <Row label={t('w6h.f.received')}>
          {pairing ? t('w6h.write.numbers', { odkaz: odkaz ?? '–', pairing }) : (odkaz ?? '–')}
        </Row>
        <Row label={t('w6h.write.lines')}>
          {nonStock
            ? t('w6h.write.linesNonStock', { count: goods.length, nonStock })
            : t('w6h.write.linesAll', { count: goods.length })}
        </Row>
        <Row label={t('w6h.write.warehouse')}>
          {warehouse ? `${warehouse.code} – ${warehouse.name}` : (d.warehouse_code ?? '–')}
        </Row>
        <Row label={t('w6h.write.centreSeries')}>
          {t('w6h.write.centreSeriesValue', {
            centre: d.centre_code ?? '–',
            branch: d.branch_name ?? '',
            series: d.series ?? t('w6h.write.seriesTemplate'),
          })}
        </Row>
        <Row label={t('w6h.write.total')}>{t('w6h.write.totalValue', { total: moneyNum(total, 2) })}</Row>
        <Row label={t('w6h.f.movedAt')}>{t('w6h.write.movedValue')}</Row>
        <p className="flex items-center gap-2 rounded-md bg-bg-subtle px-3 py-2">
          <Info size={14} aria-hidden="true" className="shrink-0 text-text-secondary" />
          <span className="type-caption text-text-secondary">
            {t('w6h.write.info')}
            {fees !== '0' ? ` ${t('w6h.write.fees', { sum: moneyNum(fees, 2) })}` : ''}
          </span>
        </p>
      </div>
    </Dialog>
  );
}
