import { useMutation, useQuery } from '@tanstack/react-query';
import { Search, X } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '../../components/Button';
import { Checkbox } from '../../components/Checkbox';
import { ApiError } from '../../lib/api';
import {
  confirmLine,
  moneyNum,
  nonStockLine,
  searchArticles,
  type Candidate,
  type DocLine,
  type DocumentDetail,
} from './purchasingApi';

type Pick = { article_id: string; name: string; catalog: string | null; unit: string | null };

const toPick = (c: Candidate): Pick => ({
  article_id: c.article_id,
  name: c.name,
  catalog: c.catalog ?? c.code,
  unit: c.unit,
});

/**
 * W6h line drawer „Riadok {n}“ (Figma `44:37979`, mobile sheet M13b `85:3615`): supplier text, candidates, article
 * search, unit conversion, warehouse, „Zapamätať kód dodávateľa“, „Neskladová položka“. Nothing goes to Money —
 * a learned code is only exported for the purchasing clerk (Settings 14).
 */
export function LineDrawer({
  doc,
  line,
  sheet,
  onClose,
  onSaved,
}: {
  doc: DocumentDetail;
  line: DocLine;
  sheet: boolean;
  onClose: () => void;
  onSaved: (d: DocumentDetail) => void;
}) {
  const { t } = useTranslation();
  const titleId = useId();
  const box = useRef<HTMLDivElement>(null);
  const current: Pick | null =
    line.article_id && line.article
      ? {
          article_id: line.article_id,
          name: line.article.name,
          catalog: line.article.catalog ?? line.article.code,
          unit: line.article.unit,
        }
      : null;
  const [pick, setPick] = useState<Pick | null>(current ?? (line.candidates[0] ? toPick(line.candidates[0]) : null));
  const [q, setQ] = useState('');
  const [factor, setFactor] = useState(line.unit_factor ? trimZeros(line.unit_factor) : '1');
  const [warehouse, setWarehouse] = useState<string>(line.warehouse_id ?? '');
  const [learn, setLearn] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const found = useQuery({
    queryKey: ['purchasing', 'articles', q.trim()],
    queryFn: () => searchArticles(q.trim()),
    enabled: q.trim().length >= 2,
    retry: false,
  });
  const fail = (e: unknown) =>
    setError(
      t(`w6h.errors.${e instanceof ApiError ? e.detail.code : 'generic'}`, { defaultValue: t('w6h.errors.generic') }),
    );
  const save = useMutation({
    mutationFn: () =>
      confirmLine(doc.id, line.line_no, {
        article_id: pick?.article_id ?? '',
        unit_factor: factor.replace(',', '.'),
        learn,
        warehouse_id: warehouse || null,
        version: doc.version,
      }),
    onSuccess: onSaved,
    onError: fail,
  });
  const nonStock = useMutation({
    mutationFn: () => nonStockLine(doc.id, line.line_no, doc.version),
    onSuccess: onSaved,
    onError: fail,
  });
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    box.current?.querySelector<HTMLElement>('button,input')?.focus();
    return () => opener?.focus();
  }, []);
  const factorOk = /^\d+([.,]\d{1,6})?$/.test(factor) && Number(factor.replace(',', '.')) > 0;
  const qtyOur = line.qty && factorOk ? mulDec(line.qty, factor.replace(',', '.')) : null;
  const options: Pick[] = [
    ...(current ? [current] : []),
    ...line.candidates.map(toPick).filter((c) => c.article_id !== current?.article_id),
    ...(found.data ?? [])
      .filter((a) => !a.inactive)
      .map((a) => ({ article_id: a.id, name: a.name, catalog: a.catalog ?? a.code, unit: a.unit })),
  ].filter((o, i, all) => all.findIndex((x) => x.article_id === o.article_id) === i);

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-bg-overlay" onClick={onClose}>
      <div
        ref={box}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-testid="w6h-drawer"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === 'Escape') onClose();
        }}
        className={`flex flex-col bg-bg-canvas shadow-lg ${
          sheet ? 'mt-auto max-h-[90vh] w-full rounded-t-lg' : 'h-full w-[480px] max-w-full'
        }`}
      >
        <header className="flex items-center justify-between border-b border-border-default px-5 py-4">
          <h2 id={titleId} className="type-heading text-text-primary">
            {t('w6h.drawer.title', { n: line.line_no })}
          </h2>
          <button type="button" onClick={onClose} aria-label={t('common.close')} className="text-text-secondary">
            <X size={20} aria-hidden="true" />
          </button>
        </header>
        <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto p-5">
          <section className="rounded-md border border-border-default bg-bg-subtle p-3">
            <p className="type-caption uppercase tracking-wide text-text-secondary">{t('w6h.drawer.supplierText')}</p>
            <p className="type-label text-text-primary">
              {line.supplier_code ? `${line.supplier_code} · ` : ''}
              {line.name}
            </p>
            <p className="type-caption text-text-secondary">
              {moneyNum(line.qty, 4)} {line.unit ?? ''} × {moneyNum(line.unit_price, 4)} ={' '}
              {moneyNum(line.line_total, 2)} €
            </p>
          </section>
          <fieldset className="flex flex-col gap-2">
            <legend className="type-label mb-2 text-text-primary">{t('w6h.drawer.article')}</legend>
            {options.map((o) => (
              <label
                key={o.article_id}
                className={`flex cursor-pointer items-start gap-3 rounded-md border p-3 ${
                  pick?.article_id === o.article_id
                    ? 'border-brand-primary-500 bg-brand-primary-50'
                    : 'border-border-default'
                }`}
              >
                <input
                  type="radio"
                  name="article"
                  checked={pick?.article_id === o.article_id}
                  onChange={() => setPick(o)}
                  className="mt-1 accent-brand-primary-600"
                />
                <span className="type-small flex flex-col">
                  <span className="text-text-primary">
                    {o.name} <span className="text-text-secondary">{o.catalog ?? ''}</span>
                  </span>
                  {o.unit ? <span className="text-text-tertiary">{o.unit}</span> : null}
                </span>
              </label>
            ))}
            <label className="relative">
              <Search size={16} aria-hidden="true" className="absolute left-3 top-2.5 text-text-tertiary" />
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder={t('w6h.drawer.search')}
                aria-label={t('w6h.drawer.search')}
                data-testid="w6h-article-search"
                className="type-body h-9 w-full rounded-md bg-bg-muted pl-9 pr-3 placeholder:text-text-tertiary"
              />
            </label>
            {found.isError ? <p className="type-caption text-danger-600">{t('w6h.errors.search')}</p> : null}
          </fieldset>
          <div className="grid grid-cols-2 gap-3">
            <label className="type-label flex flex-col gap-1">
              {t('w6h.drawer.factor', { unit: line.unit ?? '–', target: pick?.unit ?? '–' })}
              <input
                value={factor}
                onChange={(e) => setFactor(e.target.value)}
                inputMode="decimal"
                aria-invalid={!factorOk}
                data-testid="w6h-factor"
                className="type-body h-9 rounded-sm border border-border-default px-2"
              />
            </label>
            <div className="type-label flex flex-col gap-1">
              {t('w6h.cols.qty')}
              <output
                className="type-body flex h-9 items-center rounded-sm border border-border-default bg-bg-muted px-2"
                data-testid="w6h-qty-our"
              >
                {moneyNum(qtyOur, 4)}
              </output>
            </div>
          </div>
          <label className="type-label flex flex-col gap-1">
            {t('w6h.cols.warehouse')}
            <select
              value={warehouse}
              onChange={(e) => setWarehouse(e.target.value)}
              className="type-body h-9 rounded-sm border border-border-default bg-bg-canvas px-2"
            >
              <option value="">{t('w6h.drawer.branchWarehouse')}</option>
              {doc.warehouses.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.code} – {w.name}
                </option>
              ))}
            </select>
          </label>
          {line.supplier_code ? (
            <div className="flex flex-col gap-1">
              <Checkbox checked={learn} onChange={(e) => setLearn(e.target.checked)} label={t('w6h.drawer.learn')} />
              <p className="type-caption pl-6 text-text-secondary">
                {t('w6h.drawer.learnHint', {
                  code: line.supplier_code,
                  supplier: doc.supplier?.name ?? doc.supplier_name ?? '',
                })}
              </p>
            </div>
          ) : null}
          {error ? (
            <p role="alert" className="type-small text-danger-600">
              {error}
            </p>
          ) : null}
        </div>
        <footer className="flex items-center gap-2 border-t border-border-default px-5 py-4">
          <button
            type="button"
            className="type-label mr-auto text-brand-primary-600"
            onClick={() => nonStock.mutate()}
            disabled={nonStock.isPending}
            data-testid="w6h-non-stock"
          >
            {t('w6h.nonStockAction')}
          </button>
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button onClick={() => save.mutate()} disabled={!pick || !factorOk || save.isPending} data-testid="w6h-apply">
            {t('w6h.drawer.apply')}
          </Button>
        </footer>
      </div>
    </div>
  );
}

/** qty × factor on decimal strings (no floats). */
function mulDec(a: string, b: string): string {
  const parts = (s: string) => {
    const [w = '0', f = ''] = s.split('.');
    return { v: BigInt(w + f), n: f.length };
  };
  const x = parts(a);
  const y = parts(b);
  const n = x.n + y.n;
  const digits = (x.v * y.v).toString().padStart(n + 1, '0');
  return n ? `${digits.slice(0, -n)}.${digits.slice(-n)}` : digits;
}

function trimZeros(s: string): string {
  return s.includes('.') ? s.replace(/0+$/, '').replace(/\.$/, '') : s;
}
