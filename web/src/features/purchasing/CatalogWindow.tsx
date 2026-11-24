import { useInfiniteQuery } from '@tanstack/react-query';
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Columns3, Globe, Plus, Search, X } from 'lucide-react';
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '../../components/Button';
import { ApiError } from '../../lib/api';
import {
  CATALOG_PAGE,
  fetchCatalog,
  moneyNum,
  type CatalogRow,
  type CatalogSort,
  type DocumentDetail,
  type StockRow,
} from './purchasingApi';

/** Columns of the Katalóg grid — the ones Smart Mail reads reliably from Money (Erik 24 Nov 2026, „Výber stĺpcov“). */
const CATALOG_COLUMNS = [
  'eshop',
  'catalog',
  'name',
  'plu',
  'last_price',
  'stock',
  'unit',
  'code',
  'ean',
  'stock_total',
  'reserved',
  'ordered',
] as const;
export type CatalogColumn = (typeof CATALOG_COLUMNS)[number];
const DEFAULT_COLUMNS: CatalogColumn[] = ['eshop', 'catalog', 'name', 'plu', 'last_price', 'stock', 'unit'];
const STORAGE_KEY = 'smartmail.w6h.catalog.columns';
const WIDTH: Record<CatalogColumn, string> = {
  eshop: 'w-9',
  catalog: 'w-36',
  name: 'min-w-[14rem]',
  plu: 'w-28',
  last_price: 'w-32',
  stock: 'w-32',
  unit: 'w-12',
  code: 'w-28',
  ean: 'w-36',
  stock_total: 'w-32',
  reserved: 'w-28',
  ordered: 'w-28',
};
const NUMERIC = new Set<CatalogColumn>(['last_price', 'stock', 'stock_total', 'reserved', 'ordered']);
/** Columns the server can sort by (the read cache `money_articles`); stock columns are live per page. */
const SORTABLE = new Set<CatalogColumn>(['catalog', 'name', 'plu', 'last_price']);

function loadColumns(): CatalogColumn[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    const list = raw ? (JSON.parse(raw) as unknown) : null;
    if (Array.isArray(list)) {
      const known = list.filter((c): c is CatalogColumn => CATALOG_COLUMNS.includes(c as CatalogColumn));
      if (known.includes('name')) return known;
    }
  } catch {
    /* private window / blocked storage — the defaults */
  }
  return DEFAULT_COLUMNS;
}

function saveColumns(cols: CatalogColumn[]) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(cols));
  } catch {
    /* a per-viewer convenience only */
  }
}

/** Σ of decimal strings without floats (4 dp is enough for stock quantities). */
function sumDec(values: string[]): string {
  const scale = 10000n;
  const toInt = (v: string) => {
    const neg = v.startsWith('-');
    const [w = '0', f = ''] = v.replace('-', '').split('.');
    const n = BigInt(w) * scale + BigInt((f + '0000').slice(0, 4));
    return neg ? -n : n;
  };
  const total = values.reduce((acc, v) => acc + toInt(v), 0n);
  const neg = total < 0n;
  const abs = neg ? -total : total;
  return `${neg ? '-' : ''}${abs / scale}.${(abs % scale).toString().padStart(4, '0')}`;
}

export type CatalogPick = {
  id: string;
  name: string;
  catalog: string | null;
  unit: string | null;
  kind: 'article' | 'variant';
};
export type CatalogMain = { id: string; name: string; catalog: string };

/**
 * W6h „Katalóg“ (Figma 264:91756, výber stĺpcov 265:92125, mobil M13b 265:99286): a bigger article search in the
 * look of the Money catalog — main cards (not selectable, DL-B11) followed by their italic variants, stock of every
 * warehouse for the selected row (information only — D18), column chooser remembered in this browser.
 */
export function CatalogWindow({
  doc,
  initialQuery,
  initialWarehouse,
  mobile,
  canCreate,
  onClose,
  onPick,
  onCreateVariant,
  onCreateMain,
}: {
  doc: DocumentDetail;
  initialQuery: string;
  initialWarehouse: string | null;
  mobile: boolean;
  canCreate: boolean;
  onClose: () => void;
  onPick: (p: CatalogPick) => void;
  onCreateVariant: (main: CatalogMain) => void;
  onCreateMain: () => void;
}) {
  const { t } = useTranslation();
  const titleId = useId();
  const box = useRef<HTMLDivElement>(null);
  const [q, setQ] = useState(initialQuery);
  const [debounced, setDebounced] = useState(initialQuery.trim());
  const [warehouse, setWarehouse] = useState<string>(initialWarehouse ?? doc.warehouses[0]?.id ?? '');
  const [selected, setSelected] = useState<string | null>(null);
  const [columns, setColumns] = useState<CatalogColumn[]>(loadColumns);
  const [chooser, setChooser] = useState(false);
  const [sort, setSort] = useState<{ by: CatalogSort; desc: boolean }>({ by: 'catalog', desc: false });
  const scroller = useRef<HTMLDivElement>(null);
  const sentinel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(q.trim()), 300);
    return () => window.clearTimeout(id);
  }, [q]);
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    box.current?.querySelector<HTMLInputElement>('input[data-autofocus]')?.focus();
    return () => opener?.focus();
  }, []);
  // the whole catalog from the read cache, 100 rows a page, the next page when the end of the list comes into view
  const found = useInfiniteQuery({
    queryKey: ['purchasing', 'catalog', debounced, sort.by, sort.desc],
    queryFn: ({ pageParam }) => fetchCatalog({ q: debounced, sort: sort.by, desc: sort.desc, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, p) => n + p.items.length, 0);
      return last.cached && last.items.length === CATALOG_PAGE && loaded < last.total ? loaded : undefined;
    },
    retry: false,
  });
  const pages = found.data?.pages ?? [];
  const first = pages[0];
  const cached = first?.cached ?? true;
  const total = first?.total ?? 0;
  const stockAvailable = pages.every((p) => p.stock_available);
  const rows = useMemo(
    () => (found.data?.pages ?? []).flatMap((p) => p.items).filter((r) => !r.inactive),
    [found.data],
  );
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = found;
  useEffect(() => {
    const el = sentinel.current;
    if (!el || !hasNextPage || typeof IntersectionObserver === 'undefined') return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting) && !isFetchingNextPage) void fetchNextPage();
      },
      { root: scroller.current, rootMargin: '200px' },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage, rows.length]);
  const toggleSort = (c: CatalogColumn) => {
    if (!SORTABLE.has(c)) return;
    const by = c as CatalogSort;
    setSort((s) => (s.by === by ? { by, desc: !s.desc } : { by, desc: false }));
    scroller.current?.scrollTo({ top: 0 });
  };
  const current = rows.find((r) => r.id === selected) ?? null;
  const warehouseOf = (r: CatalogRow): StockRow | undefined => r.stocks.find((s) => s.warehouse_id === warehouse);
  const whLabel = (() => {
    const w = doc.warehouses.find((x) => x.id === warehouse);
    return w ? `${w.code} – ${w.name}` : '';
  })();
  // „Založiť variant k …“: the selected main card, or the main card of the selected variant
  const mainFor = (r: CatalogRow | null): CatalogMain | null => {
    if (!r) return null;
    if (r.kind === 'main') return { id: r.id, name: r.name, catalog: r.catalog ?? r.code ?? '' };
    const main = rows.find((x) => x.id === r.parent_id);
    return main ? { id: main.id, name: main.name, catalog: main.catalog ?? main.code ?? '' } : null;
  };
  const main = mainFor(current);
  const pickable = current && current.kind !== 'main';
  const pick = (r: CatalogRow) => {
    if (r.kind === 'main') return;
    onPick({
      id: r.id,
      name: r.name,
      catalog: r.catalog ?? r.code,
      unit: r.unit,
      kind: r.kind === 'variant' ? 'variant' : 'article',
    });
  };
  const errorCode = found.error instanceof ApiError ? found.error.detail.code : found.isError ? 'generic' : null;

  function cell(r: CatalogRow, c: CatalogColumn) {
    const stock = warehouseOf(r);
    switch (c) {
      case 'eshop':
        return r.eshop ? <Globe size={14} aria-label={t('w6h.catalog.eshop')} className="text-text-secondary" /> : null;
      case 'catalog':
        return <span className={r.kind === 'variant' ? 'italic' : undefined}>{r.catalog ?? ''}</span>;
      case 'name':
        return (
          <span className="flex min-w-0 items-center gap-2">
            <span
              className={`truncate ${r.kind === 'variant' ? 'pl-4 italic' : ''} ${r.kind === 'main' ? 'font-medium' : ''}`}
            >
              {r.name}
            </span>
            {r.kind === 'main' ? (
              <span className="type-caption shrink-0 rounded-full bg-bg-muted px-2 py-0.5 text-text-secondary">
                {t('w6h.drawer.mainCard')}
              </span>
            ) : null}
          </span>
        );
      case 'plu':
        return <span className={`text-text-secondary ${r.kind === 'variant' ? 'italic' : ''}`}>{r.plu ?? '—'}</span>;
      case 'last_price':
        return r.last_price ? moneyNum(r.last_price, 4) : '—';
      case 'stock':
        return stock ? moneyNum(stock.qty, 4) : '—';
      case 'unit':
        return <span className="text-text-secondary">{r.unit ?? ''}</span>;
      case 'code':
        return r.code ?? '';
      case 'ean':
        return r.ean ?? '';
      case 'stock_total':
        return r.stocks.length ? moneyNum(sumDec(r.stocks.map((s) => s.qty)), 4) : '—';
      case 'reserved':
        return stock ? moneyNum(stock.reserved, 4) : '—';
      case 'ordered':
        return stock ? moneyNum(stock.ordered, 4) : '—';
    }
  }

  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Escape' && !chooser) {
      e.stopPropagation();
      onClose();
    }
  };
  const header = (
    <header className="flex items-start gap-3 px-6 pb-3 pt-4">
      <div className="min-w-0 flex-1">
        <h2 id={titleId} className="type-title text-text-primary">
          {t('w6h.catalog.title')}
        </h2>
      </div>
      <button type="button" onClick={onClose} aria-label={t('common.close')} className="p-1 text-text-secondary">
        <X size={20} aria-hidden="true" />
      </button>
    </header>
  );
  const search = (
    <label className="relative min-w-0 flex-1">
      <Search size={16} aria-hidden="true" className="absolute left-3 top-2.5 text-text-tertiary" />
      <input
        data-autofocus
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder={t('w6h.catalog.search')}
        aria-label={t('w6h.catalog.search')}
        data-testid="w6h-catalog-search"
        className="type-body h-9 w-full rounded-md border border-border-default bg-bg-canvas pl-9 pr-3 placeholder:text-text-tertiary"
      />
    </label>
  );
  const warehouseSelect = (
    <select
      value={warehouse}
      onChange={(e) => setWarehouse(e.target.value)}
      aria-label={t('w6h.catalog.stockOf')}
      data-testid="w6h-catalog-warehouse"
      className="type-body h-9 rounded-md border border-border-default bg-bg-canvas px-2"
    >
      {doc.warehouses.map((w) => (
        <option key={w.id} value={w.id}>
          {t('w6h.catalog.stockOfValue', { warehouse: `${w.code} – ${w.name}` })}
        </option>
      ))}
    </select>
  );
  const status = (
    <p className="type-caption px-6 pb-2 pt-1 text-text-tertiary" data-testid="w6h-catalog-status">
      {found.isPending || (found.isFetching && !isFetchingNextPage)
        ? t('w6h.catalog.loading')
        : errorCode
          ? t(`w6h.errors.${errorCode}`, { defaultValue: t('w6h.errors.search') })
          : !cached && debounced.length < 2
            ? t('w6h.catalog.hint')
            : rows.length === 0
              ? t('w6h.catalog.empty')
              : cached && !debounced
                ? t('w6h.catalog.all', { count: total })
                : t('w6h.catalog.count', { count: total })}
      {!cached && debounced.length >= 2 ? ` · ${t('w6h.catalog.notSynced')}` : ''}
      {first && !stockAvailable ? ` · ${t('w6h.catalog.stockOffline')}` : ''}
    </p>
  );
  const stockPanel = current ? (
    <section className="border-t border-border-default px-6 py-3" data-testid="w6h-catalog-stock">
      <p className="type-label mb-2 text-text-primary">
        {t('w6h.catalog.stockTitle', { name: current.name })}{' '}
        <span className="type-caption font-normal text-text-tertiary">{t('w6h.catalog.stockInfo')}</span>
      </p>
      {current.stocks.length === 0 ? (
        <p className="type-caption text-text-secondary">{t('w6h.catalog.noStock')}</p>
      ) : mobile ? (
        <p className="type-caption text-text-secondary">
          {current.stocks
            .map((s) => `${s.code ?? ''}${s.name ? ` – ${s.name}` : ''}: ${moneyNum(s.qty, 0)}`)
            .join(' · ')}
        </p>
      ) : (
        <table className="type-small w-full max-w-3xl tabular-nums">
          <thead className="bg-bg-subtle text-text-secondary">
            <tr>
              {(['warehouse', 'qty', 'reserved', 'ordered', 'expected', 'unitPrice'] as const).map((k) => (
                <th key={k} className={`px-2 py-1 font-normal ${k === 'warehouse' ? 'text-left' : 'text-right'}`}>
                  {t(`w6h.catalog.stockCols.${k}`)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {current.stocks.map((s) => (
              <tr key={s.warehouse_id} className="border-b border-border-default">
                <td className="px-2 py-0.5">
                  {s.code}
                  {s.name ? ` – ${s.name}` : ''}
                </td>
                <td className="px-2 py-0.5 text-right">{moneyNum(s.qty, 4)}</td>
                <td className="px-2 py-0.5 text-right">{moneyNum(s.reserved, 4)}</td>
                <td className="px-2 py-0.5 text-right">{moneyNum(s.ordered, 4)}</td>
                <td className="px-2 py-0.5 text-right">{moneyNum(s.expected, 4)}</td>
                <td className="px-2 py-0.5 text-right">{s.unit_price ? moneyNum(s.unit_price, 4) : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  ) : null;
  const footer = (
    <footer className="flex flex-wrap items-center gap-2 border-t border-border-default px-4 py-3 md:px-6">
      {canCreate ? (
        <>
          <button
            type="button"
            disabled={!main}
            onClick={() => main && onCreateVariant(main)}
            className="type-label inline-flex items-center gap-1 px-2 text-brand-primary-600 disabled:text-text-tertiary"
            data-testid="w6h-catalog-new-variant"
          >
            <Plus size={16} aria-hidden="true" />
            {main ? t('w6h.catalog.newVariantOf', { name: main.name }) : t('w6h.catalog.newVariant')}
          </button>
          {mobile ? null : (
            <button
              type="button"
              onClick={onCreateMain}
              className="type-label inline-flex items-center gap-1 px-2 text-brand-primary-600"
              data-testid="w6h-catalog-new-main"
            >
              <Plus size={16} aria-hidden="true" />
              {t('w6h.catalog.newMain')}
            </button>
          )}
        </>
      ) : null}
      <span className="ml-auto flex gap-2">
        {mobile ? null : (
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
        )}
        <Button disabled={!pickable} onClick={() => current && pick(current)} data-testid="w6h-catalog-pick">
          {t('w6h.catalog.pick')}
        </Button>
      </span>
    </footer>
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-bg-overlay md:p-6"
      onClick={(e) => {
        e.stopPropagation(); // the drawer behind must stay open
        onClose();
      }}
    >
      <div
        ref={box}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-testid="w6h-catalog"
        onKeyDown={onKey}
        onClick={(e) => e.stopPropagation()}
        className={`flex flex-col bg-bg-canvas shadow-e3 ${
          mobile ? 'h-full w-full' : 'h-[min(900px,100%)] w-[min(1080px,100%)] rounded-lg'
        }`}
      >
        {header}
        <div className="flex flex-wrap items-center gap-2 px-6">
          {search}
          {mobile ? null : warehouseSelect}
          {mobile ? null : (
            <Button variant="secondary" onClick={() => setChooser(true)} data-testid="w6h-catalog-columns">
              <Columns3 size={16} aria-hidden="true" />
              {t('w6h.catalog.columns')}
            </Button>
          )}
        </div>
        {mobile ? <div className="px-6 pt-2">{warehouseSelect}</div> : null}
        {status}
        <div ref={scroller} className="min-h-0 flex-1 overflow-auto px-0 md:px-6">
          {mobile ? (
            <ul className="border-t border-border-default" data-testid="w6h-catalog-rows">
              {rows.map((r) => {
                const on = r.id === selected;
                const stock = warehouseOf(r);
                return (
                  <li
                    key={r.id}
                    data-testid={`w6h-catalog-row-${r.kind}`}
                    onClick={() => setSelected(r.id)}
                    className={`flex cursor-pointer flex-col gap-0.5 border-b border-border-default py-2 pr-4 ${
                      r.kind === 'variant' ? 'pl-8' : 'pl-4'
                    } ${on ? 'bg-brand-primary-100' : ''}`}
                  >
                    <span className="flex items-center gap-2">
                      <span className="type-body min-w-0 flex-1 truncate">
                        {/* the `type-body` font shorthand would reset `italic`, so it sits on the inner element */}
                        <span
                          className={`${r.kind === 'variant' ? 'italic' : ''} ${r.kind === 'main' ? 'font-medium' : ''}`}
                        >
                          {r.name}
                        </span>
                      </span>
                      {r.kind === 'main' ? (
                        <span className="type-caption rounded-full bg-bg-muted px-2 py-0.5 text-text-secondary">
                          {t('w6h.drawer.mainCard')}
                        </span>
                      ) : null}
                    </span>
                    <span className="type-caption text-text-secondary">
                      {[
                        r.catalog,
                        stock ? t('w6h.catalog.stockShort', { qty: moneyNum(stock.qty, 0), unit: r.unit ?? '' }) : null,
                        r.last_price ? `${moneyNum(r.last_price, 4)} €` : null,
                      ]
                        .filter(Boolean)
                        .join(' · ')}
                    </span>
                  </li>
                );
              })}
            </ul>
          ) : (
            <table className="type-small w-full border-collapse" data-testid="w6h-catalog-rows">
              <thead className="sticky top-0 z-10 bg-bg-subtle text-text-secondary">
                <tr>
                  {columns.map((c) => {
                    const label =
                      c === 'stock'
                        ? t('w6h.catalog.cols.stockOf', { warehouse: whLabel })
                        : t(`w6h.catalog.cols.${c}`);
                    const active = sort.by === c;
                    return (
                      <th
                        key={c}
                        scope="col"
                        aria-sort={active ? (sort.desc ? 'descending' : 'ascending') : undefined}
                        className={`${WIDTH[c]} whitespace-nowrap border-b border-border-default px-1.5 py-1.5 font-medium ${
                          NUMERIC.has(c) ? 'text-right' : 'text-left'
                        }`}
                      >
                        {SORTABLE.has(c) && cached ? (
                          <button
                            type="button"
                            onClick={() => toggleSort(c)}
                            data-testid={`w6h-catalog-sort-${c}`}
                            className={`inline-flex items-center gap-1 ${active ? 'text-text-primary' : ''}`}
                          >
                            {label}
                            {active ? (
                              sort.desc ? (
                                <ArrowDown size={12} aria-hidden="true" />
                              ) : (
                                <ArrowUp size={12} aria-hidden="true" />
                              )
                            ) : null}
                          </button>
                        ) : (
                          label
                        )}
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const on = r.id === selected;
                  return (
                    <tr
                      key={r.id}
                      data-testid={`w6h-catalog-row-${r.kind}`}
                      aria-selected={on}
                      onClick={() => setSelected(r.id)}
                      onDoubleClick={() => pick(r)}
                      className={`cursor-pointer border-b border-border-default ${
                        on ? 'bg-brand-primary-100' : 'hover:bg-bg-subtle'
                      }`}
                    >
                      {columns.map((c) => (
                        <td
                          key={c}
                          className={`max-w-0 px-1.5 py-1 ${NUMERIC.has(c) ? 'text-right tabular-nums' : 'text-left'} ${
                            c === 'name' ? '' : 'whitespace-nowrap'
                          }`}
                        >
                          {cell(r, c)}
                        </td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
          {hasNextPage ? (
            <div ref={sentinel} className="flex justify-center py-3">
              <Button
                variant="secondary"
                disabled={isFetchingNextPage}
                onClick={() => void fetchNextPage()}
                data-testid="w6h-catalog-more"
              >
                {isFetchingNextPage ? t('w6h.catalog.loading') : t('w6h.catalog.more', { shown: rows.length, total })}
              </Button>
            </div>
          ) : null}
        </div>
        {stockPanel}
        {footer}
      </div>
      {chooser ? (
        <ColumnChooser
          value={columns}
          onCancel={() => setChooser(false)}
          onSave={(cols) => {
            setColumns(cols);
            saveColumns(cols);
            setChooser(false);
          }}
        />
      ) : null}
    </div>
  );
}

/** „Výber stĺpcov“ like in Money: hidden / visible lists, move with the arrows, order with up / down. */
function ColumnChooser({
  value,
  onCancel,
  onSave,
}: {
  value: CatalogColumn[];
  onCancel: () => void;
  onSave: (cols: CatalogColumn[]) => void;
}) {
  const { t } = useTranslation();
  const titleId = useId();
  const [visible, setVisible] = useState<CatalogColumn[]>(value);
  const [focus, setFocus] = useState<CatalogColumn | null>(null);
  const hidden = CATALOG_COLUMNS.filter((c) => !visible.includes(c));
  const show = (c: CatalogColumn | null) => c && hidden.includes(c) && setVisible([...visible, c]);
  const hide = (c: CatalogColumn | null) => c && c !== 'name' && setVisible(visible.filter((x) => x !== c));
  const move = (dir: -1 | 1) => {
    if (!focus) return;
    const i = visible.indexOf(focus);
    const j = i + dir;
    if (i < 0 || j < 0 || j >= visible.length) return;
    const next = [...visible];
    [next[i], next[j]] = [next[j] as CatalogColumn, next[i] as CatalogColumn];
    setVisible(next);
  };
  const list = (title: string, items: readonly CatalogColumn[], testId: string) => (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-md border border-border-default">
      <p className="type-caption bg-bg-subtle px-3 py-1.5 text-text-secondary">{title}</p>
      <ul role="listbox" aria-label={title} className="min-h-0 flex-1 overflow-auto" data-testid={testId}>
        {items.map((c) => (
          <li
            key={c}
            role="option"
            aria-selected={focus === c}
            onClick={() => setFocus(c)}
            onDoubleClick={() => (hidden.includes(c) ? show(c) : hide(c))}
            className={`type-small cursor-pointer px-3 py-1 ${focus === c ? 'bg-brand-primary-100' : 'hover:bg-bg-subtle'}`}
          >
            {t(`w6h.catalog.chooser.${c}`)}
          </li>
        ))}
      </ul>
    </div>
  );
  const arrow = (label: string, icon: ReactNode, onClick: () => void) => (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className="flex h-8 w-8 items-center justify-center rounded-md border border-border-default bg-bg-canvas text-text-primary"
    >
      {icon}
    </button>
  );
  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-bg-overlay p-4"
      onClick={(e) => e.stopPropagation()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-testid="w6h-catalog-chooser"
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            e.stopPropagation();
            onCancel();
          }
        }}
        className="flex h-[min(600px,100%)] w-[min(680px,100%)] flex-col gap-3 rounded-lg bg-bg-canvas p-6 shadow-e3"
      >
        <h3 id={titleId} className="type-heading text-text-primary">
          {t('w6h.catalog.chooser.title')}
        </h3>
        <div className="flex min-h-0 flex-1 gap-3">
          {list(t('w6h.catalog.chooser.hidden'), hidden, 'w6h-chooser-hidden')}
          <div className="flex flex-col justify-center gap-2">
            {arrow(t('w6h.catalog.chooser.show'), <ChevronRight size={16} />, () => show(focus))}
            {arrow(t('w6h.catalog.chooser.hide'), <ChevronLeft size={16} />, () => hide(focus))}
            {arrow(t('w6h.catalog.chooser.up'), <ArrowUp size={16} />, () => move(-1))}
            {arrow(t('w6h.catalog.chooser.down'), <ArrowDown size={16} />, () => move(1))}
          </div>
          {list(t('w6h.catalog.chooser.visible'), visible, 'w6h-chooser-visible')}
        </div>
        <p className="type-caption text-text-tertiary">{t('w6h.catalog.chooser.note')}</p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="type-label text-brand-primary-600"
            onClick={() => setVisible(DEFAULT_COLUMNS)}
          >
            {t('w6h.catalog.chooser.reset')}
          </button>
          <span className="ml-auto flex gap-2">
            <Button variant="secondary" onClick={onCancel}>
              {t('common.cancel')}
            </Button>
            <Button onClick={() => onSave(visible)} data-testid="w6h-chooser-ok">
              {t('w6h.catalog.chooser.ok')}
            </Button>
          </span>
        </div>
      </div>
    </div>
  );
}
