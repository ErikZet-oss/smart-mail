import { useMutation, useQuery } from '@tanstack/react-query';
import { ChevronDown, Plus, Search } from 'lucide-react';
import { useEffect, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Banner } from '../../components/Banner';
import { Button } from '../../components/Button';
import { useToasts } from '../../components/toastContext';
import { ApiError } from '../../lib/api';
import {
  catalogFree,
  catalogProposal,
  createArticle,
  moneyNum,
  searchArticles,
  type DocLine,
  type DocumentDetail,
  type NewArticleBody,
  type NewArticleResult,
} from './purchasingApi';
import { sizeOf, withoutSize } from './newArticleText';

export type Parent = { kind: 'existing'; id: string; name: string; catalog: string } | { kind: 'new' };
type Check = 'idle' | 'checking' | 'free' | 'taken' | 'error';

const UNSAFE = /[~#|()]/;

/** Debounced live check of a catalog in Money (SCREENS_SPEC W6h „Nový artikel v Money“). */
function useCatalogCheck(value: string, enabled: boolean): Check {
  const [debounced, setDebounced] = useState(value.trim());
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value.trim()), 350);
    return () => window.clearTimeout(id);
  }, [value]);
  const valid = enabled && debounced.length > 0 && !UNSAFE.test(debounced);
  const q = useQuery({
    queryKey: ['purchasing', 'catalog-free', debounced],
    queryFn: () => catalogFree(debounced),
    enabled: valid,
    retry: false,
    staleTime: 5_000,
  });
  if (!enabled || !value.trim()) return 'idle';
  if (debounced !== value.trim() || q.isFetching) return 'checking';
  if (!valid) return 'error';
  if (q.isError) return 'error';
  if (!q.data) return 'checking';
  return q.data.free ? 'free' : 'taken';
}

const FIELD =
  'type-body h-9 w-full rounded-sm border bg-bg-canvas px-2.5 text-text-primary placeholder:text-text-tertiary disabled:bg-bg-muted disabled:text-text-secondary';

function Field({
  label,
  value,
  onChange,
  help,
  check,
  disabled,
  max,
  testId,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  help?: string;
  check?: Check;
  disabled?: boolean;
  max: number;
  testId: string;
}) {
  const { t } = useTranslation();
  const id = useId();
  const taken = check === 'taken';
  const note = taken
    ? t('w6h.newArticle.catalogTaken')
    : check === 'checking'
      ? t('w6h.newArticle.checking')
      : check === 'error'
        ? t('w6h.newArticle.checkFailed')
        : help;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="type-label text-text-primary">
        {label}
      </label>
      <input
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        maxLength={max}
        aria-invalid={taken || undefined}
        aria-describedby={note ? `${id}-note` : undefined}
        data-testid={testId}
        className={`${FIELD} ${taken ? 'border-danger-600' : 'border-border-default'}`}
      />
      {note ? (
        <p
          id={`${id}-note`}
          className={`type-caption ${taken ? 'text-danger-600' : 'text-text-secondary'}`}
          data-testid={`${testId}-note`}
        >
          {note}
        </p>
      ) : null}
    </div>
  );
}

/**
 * Drawer view „Nový artikel v Money“ (D32, SCREENS_SPEC W6h; Figma `255:91329` variant, `255:92189` catalog taken,
 * `256:90924` new main card + variant; mobile M13b = the same in the bottom sheet). Body + footer of the line drawer.
 */
export function NewArticleForm({
  doc,
  line,
  onBack,
  onCancel,
  onDocument,
  onCreated,
  initial,
}: {
  doc: DocumentDetail;
  line: DocLine;
  onBack: () => void;
  onCancel: () => void;
  onDocument: (d: DocumentDetail) => void;
  onCreated: (r: NewArticleResult) => void;
  /** W6h Katalóg: „Založiť variant k …“ opens with that main card, „Nová hlavná karta“ in the main-card mode. */
  initial?: { mode: 'main' | 'variant'; parent?: Parent };
}) {
  const { t } = useTranslation();
  const toasts = useToasts();
  const partial = line.new_article?.status === 'partial' && line.new_article.main ? line.new_article : null;
  const [mode, setMode] = useState<'main' | 'variant'>(partial ? 'variant' : (initial?.mode ?? 'main'));
  const [parent, setParent] = useState<Parent | null>(partial ? { kind: 'new' } : (initial?.parent ?? null));
  const [mainName, setMainName] = useState(partial?.main?.nazev ?? withoutSize(line.name));
  const [mainCatalog, setMainCatalog] = useState(partial?.main?.katalog ?? '');
  const [name, setName] = useState(line.name);
  const [typed, setTyped] = useState('');
  const [touched, setTouched] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [q, setQ] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [takenOnSubmit, setTakenOnSubmit] = useState<string | null>(null);

  const variant = mode === 'variant';
  const newMain = variant && parent?.kind === 'new';
  const ownMain = mode === 'main' || newMain; // a main card is created (or was, when partial)
  const size = sizeOf(line.name);

  // proposal of the variant catalog: main catalog + 5-digit size; recomputed when the main catalog changes
  const [mainDebounced, setMainDebounced] = useState(mainCatalog.trim());
  useEffect(() => {
    const id = window.setTimeout(() => setMainDebounced(mainCatalog.trim()), 350);
    return () => window.clearTimeout(id);
  }, [mainCatalog]);
  const parentId = parent?.kind === 'existing' ? parent.id : undefined;
  const proposal = useQuery({
    queryKey: ['purchasing', 'catalog-proposal', parentId ?? '', newMain ? mainDebounced : '', line.name],
    queryFn: () =>
      catalogProposal(parentId ? { parentId, size: line.name } : { mainCatalog: mainDebounced, size: line.name }),
    enabled: variant && size !== null && (Boolean(parentId) || (newMain && mainDebounced.length > 0)),
    retry: false,
  });
  // the proposal fills the variant catalog until the person types there (always editable)
  const catalog = variant && !touched ? (proposal.data?.katalog ?? typed) : typed;

  const mainCheck = useCatalogCheck(mainCatalog, ownMain && !partial);
  const catalogCheck = useCatalogCheck(catalog, true);
  const shownMainCheck: Check = takenOnSubmit && takenOnSubmit === mainCatalog.trim() ? 'taken' : mainCheck;
  // the single Názov / Katalóg pair: the main card („Hlavná karta“) or the variant
  const shownVarCheck: Check = takenOnSubmit && takenOnSubmit === catalog.trim() ? 'taken' : catalogCheck;

  const found = useQuery({
    queryKey: ['purchasing', 'articles', q.trim()],
    queryFn: () => searchArticles(q.trim()),
    enabled: pickerOpen && q.trim().length >= 2,
    retry: false,
  });
  const mains = (found.data ?? []).filter((a) => !a.inactive && a.kind !== 'variant');

  const submit = useMutation({
    mutationFn: () => {
      let body: NewArticleBody;
      const mainCard = { katalog: mainCatalog.trim(), nazev: mainName.trim() };
      const variantCard = { katalog: catalog.trim(), nazev: name.trim() };
      if (mode === 'main') body = { mode: 'main', main: { katalog: catalog.trim(), nazev: name.trim() }, version: 0 };
      else if (parent?.kind === 'existing')
        body = { mode: 'variant', parent_id: parent.id, variant: variantCard, version: 0 };
      else body = { mode: 'main_and_variant', main: mainCard, variant: variantCard, version: 0 };
      return createArticle(doc.id, line.line_no, { ...body, version: doc.version });
    },
    onSuccess: (r) => {
      setError(null);
      if (r.status === 'partial') {
        onDocument(r.document); // the line now carries the partial state → banner + read-only main card
        return;
      }
      const card = r.variant ?? r.main;
      toasts.success(t('w6h.newArticle.created', { katalog: card?.katalog ?? '' }));
      onCreated(r);
    },
    onError: (e) => {
      const code = e instanceof ApiError ? e.detail.code : 'generic';
      if (code === 'catalog_exists' && e instanceof ApiError) {
        setTakenOnSubmit(String(e.detail.katalog ?? ''));
        return;
      }
      setError(t(`w6h.newArticle.errors.${code}`, { defaultValue: t('w6h.newArticle.errors.generic') }));
    },
  });

  const ok = (c: Check) => c === 'free';
  const valid =
    mode === 'main'
      ? name.trim() !== '' && ok(shownVarCheck)
      : parent !== null &&
        name.trim() !== '' &&
        ok(shownVarCheck) &&
        (parent.kind === 'existing' || partial !== null || (mainName.trim() !== '' && ok(shownMainCheck))) &&
        (parent.kind !== 'new' || partial !== null || mainCatalog.trim() !== catalog.trim());

  const primary = partial
    ? t('w6h.newArticle.createVariant')
    : newMain
      ? t('w6h.newArticle.createBoth')
      : t('w6h.newArticle.create');

  const variantHelp = (() => {
    if (shownVarCheck !== 'free') return undefined;
    if (proposal.data?.katalog && proposal.data.katalog === catalog.trim() && size !== null) {
      const suffix = String(size).padStart(5, '0');
      return newMain
        ? t('w6h.newArticle.proposalNew', { size, suffix })
        : t('w6h.newArticle.proposal', { size, suffix });
    }
    return t('w6h.newArticle.free');
  })();

  return (
    <>
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-5" data-testid="w6h-new-article">
        <section className="flex flex-col gap-1 rounded-md border border-border-default bg-bg-subtle p-3">
          <p className="type-micro uppercase text-text-tertiary">{t('w6h.drawer.supplierText')}</p>
          <p className="type-body-strong text-text-primary">
            {line.supplier_code ? `${line.supplier_code} · ` : ''}
            {line.name}
          </p>
          <p className="type-caption text-text-secondary">
            {moneyNum(line.qty, 4)} {line.unit ?? ''} × {moneyNum(line.unit_price, 4)} = {moneyNum(line.line_total, 2)}{' '}
            €
          </p>
        </section>
        {partial ? (
          <Banner
            kind="danger"
            message={t('w6h.newArticle.partial', {
              katalog: partial.main?.katalog ?? '',
              error: t(`w6h.newArticle.errors.${partial.error ?? 'generic'}`, {
                defaultValue: partial.error ?? t('w6h.newArticle.errors.generic'),
              }),
            })}
          />
        ) : null}
        <div
          role="radiogroup"
          aria-label={t('w6h.newArticle.kind')}
          className="flex gap-0.5 rounded-sm bg-bg-muted p-0.5"
        >
          {(['main', 'variant'] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={mode === m}
              disabled={partial !== null}
              onClick={() => {
                setMode(m);
                setTakenOnSubmit(null);
                setTouched(false);
                setTyped('');
              }}
              data-testid={`w6h-new-${m}`}
              className={`h-7 rounded-xs px-3 ${
                mode === m ? 'type-label bg-bg-canvas text-text-primary shadow-e1' : 'type-small text-text-secondary'
              }`}
            >
              {t(`w6h.newArticle.kinds.${m}`)}
            </button>
          ))}
        </div>

        {variant ? (
          <div className="flex flex-col gap-1.5">
            <span className="type-label text-text-primary">{t('w6h.newArticle.mainCard')}</span>
            <button
              type="button"
              disabled={partial !== null}
              onClick={() => setPickerOpen((o) => !o)}
              aria-expanded={pickerOpen}
              data-testid="w6h-new-parent"
              className="flex h-9 w-full items-center gap-2 rounded-sm border border-border-default bg-bg-canvas px-2.5 text-left disabled:bg-bg-muted"
            >
              <span
                className={`type-body min-w-0 flex-1 truncate ${parent ? 'text-text-primary' : 'text-text-tertiary'}`}
              >
                {parent?.kind === 'existing'
                  ? `${parent.name} · ${parent.catalog}`
                  : parent?.kind === 'new'
                    ? t('w6h.newArticle.newMain')
                    : t('w6h.newArticle.pickMain')}
              </span>
              <ChevronDown size={16} aria-hidden="true" className="shrink-0 text-text-secondary" />
            </button>
            {pickerOpen ? (
              <div className="flex flex-col rounded-md border border-border-default" data-testid="w6h-new-parent-list">
                <label className="relative border-b border-border-default">
                  <Search size={16} aria-hidden="true" className="absolute left-3 top-2.5 text-text-tertiary" />
                  <input
                    autoFocus
                    value={q}
                    onChange={(e) => setQ(e.target.value)}
                    placeholder={t('w6h.newArticle.searchMain')}
                    aria-label={t('w6h.newArticle.searchMain')}
                    data-testid="w6h-new-parent-search"
                    className="type-body h-9 w-full bg-transparent pl-9 pr-3 placeholder:text-text-tertiary"
                  />
                </label>
                <button
                  type="button"
                  onClick={() => {
                    setParent({ kind: 'new' });
                    setPickerOpen(false);
                    setTouched(false);
                  }}
                  data-testid="w6h-new-parent-new"
                  className="type-small flex items-center gap-2 border-b border-border-default px-3 py-2 text-left text-brand-primary-600 hover:bg-bg-subtle"
                >
                  <Plus size={14} aria-hidden="true" />
                  {t('w6h.newArticle.newMainOption')}
                </button>
                {mains.map((a) => (
                  <button
                    key={a.id}
                    type="button"
                    onClick={() => {
                      setParent({ kind: 'existing', id: a.id, name: a.name, catalog: a.catalog ?? a.code ?? '' });
                      setPickerOpen(false);
                      setTouched(false);
                    }}
                    data-testid="w6h-new-parent-option"
                    className="flex items-center gap-3 border-b border-border-default px-3 py-2 text-left last:border-b-0 hover:bg-bg-subtle"
                  >
                    <span className="type-small min-w-0 flex-1 truncate text-text-primary">{a.name}</span>
                    <span className="type-caption shrink-0 tabular-nums text-text-secondary">
                      {a.catalog ?? a.code}
                    </span>
                  </button>
                ))}
                {q.trim().length >= 2 && found.isSuccess && mains.length === 0 ? (
                  <p className="type-caption px-3 py-2 text-text-secondary">{t('w6h.drawer.noResults')}</p>
                ) : null}
              </div>
            ) : null}
            <p className="type-caption text-text-secondary">
              {newMain ? t('w6h.newArticle.newMainHelp') : t('w6h.newArticle.mainHelp')}
            </p>
          </div>
        ) : null}

        {newMain ? (
          <section
            className="flex flex-col gap-3 rounded-md border border-border-default bg-bg-subtle p-3"
            data-testid="w6h-new-main-box"
          >
            <p className="type-label text-text-primary">{t('w6h.newArticle.newMainTitle')}</p>
            <Field
              label={t('w6h.newArticle.mainName')}
              value={mainName}
              onChange={setMainName}
              disabled={partial !== null}
              max={200}
              testId="w6h-new-main-name"
            />
            <Field
              label={t('w6h.newArticle.mainCatalog')}
              value={mainCatalog}
              onChange={(v) => {
                setMainCatalog(v);
                setTouched(false);
                setTakenOnSubmit(null);
              }}
              check={partial ? 'idle' : shownMainCheck}
              help={
                partial
                  ? t('w6h.newArticle.mainCreated')
                  : shownMainCheck === 'free'
                    ? t('w6h.newArticle.free')
                    : undefined
              }
              disabled={partial !== null}
              max={50}
              testId="w6h-new-main-catalog"
            />
          </section>
        ) : null}

        <Field
          label={newMain ? t('w6h.newArticle.variantName') : t('w6h.newArticle.name')}
          value={name}
          onChange={setName}
          help={t('w6h.newArticle.nameHelp')}
          max={200}
          testId="w6h-new-name"
        />
        <Field
          label={newMain ? t('w6h.newArticle.variantCatalog') : t('w6h.newArticle.catalog')}
          value={catalog}
          onChange={(v) => {
            setTyped(v);
            setTouched(true);
            setTakenOnSubmit(null);
          }}
          check={mode === 'main' ? shownVarCheck : shownVarCheck}
          help={mode === 'main' ? (shownVarCheck === 'free' ? t('w6h.newArticle.free') : undefined) : variantHelp}
          max={50}
          testId="w6h-new-catalog"
        />
        <Banner kind="info" message={t('w6h.newArticle.info')} />
        {error ? (
          <p role="alert" className="type-small text-danger-600" data-testid="w6h-new-error">
            {error}
          </p>
        ) : null}
      </div>
      <footer className="flex items-center gap-2 border-t border-border-default px-5 py-3">
        <button
          type="button"
          className="type-label mr-auto px-3 text-brand-primary-600"
          onClick={onBack}
          data-testid="w6h-new-back"
        >
          {t('w6h.newArticle.back')}
        </button>
        <Button variant="secondary" onClick={onCancel}>
          {t('common.cancel')}
        </Button>
        <Button
          onClick={() => submit.mutate()}
          disabled={!valid || submit.isPending}
          className="disabled:bg-brand-primary-600 disabled:opacity-45"
          data-testid="w6h-new-submit"
        >
          {primary}
        </Button>
      </footer>
    </>
  );
}
