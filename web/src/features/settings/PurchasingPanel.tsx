import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, Download, Lock, Plus, Search, Trash2, X } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { Banner } from '../../components/Banner';
import { Button } from '../../components/Button';
import { Dialog } from '../../components/Dialog';
import { useToasts } from '../../components/toastContext';
import { api, ApiError } from '../../lib/api';
import { day } from '../money/moneyApi';
import { INPUT } from './adminUi';

/** SETTINGS_SPEC 14 — company-wide values (org_settings `purchasing`). Money is never written from here. */
type Role = 'warehouse' | 'admin' | 'accounting' | 'sales';
type Rule = { supplier_money_id: string; warehouse_id: string };
type Purchasing = {
  price_diff_pct: string;
  qty_diff_pct: string;
  confirm_roles: Role[];
  issue_date: 'supplier' | 'approval';
  warehouse_rules: Rule[];
  branch_warehouses: string[];
  warehouses: { id: string; label: string }[];
  suppliers: { id: string; label: string }[];
};
type Mapping = {
  id: string;
  supplier_id: string;
  supplier_name: string | null;
  code: string;
  article_id: string;
  article_name: string | null;
  unit_factor: string;
  confirmed_by: string | null;
  confirmed_at: string | null;
  uses_count: number;
};

const KEY = ['settings', 'purchasing'] as const;
const URL = '/api/settings/purchasing';
const ROLES: Role[] = ['warehouse', 'admin', 'accounting', 'sales'];
const PCT = /^\d{1,3}([.,]\d{1,2})?$/;

type Form = Pick<Purchasing, 'price_diff_pct' | 'qty_diff_pct' | 'confirm_roles' | 'issue_date' | 'warehouse_rules'>;
const toForm = (p: Purchasing): Form => ({
  price_diff_pct: p.price_diff_pct,
  qty_diff_pct: p.qty_diff_pct,
  confirm_roles: p.confirm_roles,
  issue_date: p.issue_date,
  warehouse_rules: p.warehouse_rules,
});
const pctOk = (v: string) => PCT.test(v) && Number(v.replace(',', '.')) <= 100;

/** W12-14 Nastavenia › Nákup a sklad (Figma `75:68205`, chyba `75:68435`, uložené `75:68866`). */
export function PurchasingPanel() {
  const { t } = useTranslation();
  const toasts = useToasts();
  const qc = useQueryClient();
  const data = useQuery({ queryKey: KEY, queryFn: () => api<Purchasing>('GET', URL) });
  const [draft, setDraft] = useState<Form | null>(null);
  const save = useMutation({
    mutationFn: (f: Form) =>
      api<Purchasing>(
        'PUT',
        URL,
        { ...f, price_diff_pct: f.price_diff_pct.replace(',', '.'), qty_diff_pct: f.qty_diff_pct.replace(',', '.') },
        { global: false },
      ),
    onSuccess: (out) => {
      qc.setQueryData(KEY, out);
      setDraft(null);
      toasts.success(t('settings.saved'));
    },
    onError: (e) =>
      toasts.error(
        t(`settings.purchasing.errors.${e instanceof ApiError ? e.detail.code : 'generic'}`, {
          defaultValue: t('mail.errors.generic'),
        }),
      ),
  });
  if (data.isError) return <Banner kind="warning" message={t('mail.errors.generic')} />;
  if (!data.data) return null;
  const p = data.data;
  const form = draft ?? toForm(p);
  const L = (k: string) => t(`settings.purchasing.${k}`);
  const valid = pctOk(form.price_diff_pct) && pctOk(form.qty_diff_pct) && form.confirm_roles.length > 0;
  const dirty = JSON.stringify(form) !== JSON.stringify(toForm(p));
  const set = (patch: Partial<Form>) => setDraft({ ...form, ...patch });

  return (
    <div className="flex flex-col gap-8" data-testid="settings-purchasing">
      <section className="flex max-w-[764px] flex-col gap-3">
        <h2 className="type-heading text-text-primary">{L('writesTitle')}</h2>
        <Info label={L('writes')} value={L('writesValue')} />
        <Info
          label={L('defaultWarehouse')}
          value={`${L('defaultWarehouseValue')}${p.branch_warehouses.length ? ` (${p.branch_warehouses.join(', ')})` : ''}.`}
        />
        <Info label={L('movementTime')} value={L('movementTimeValue')} />
        <Info label={L('fees')} value={L('feesValue')} />
        <Info label={L('returns')} value={L('returnsValue')} />
      </section>

      <section className="flex max-w-[764px] flex-col gap-4">
        <h2 className="type-heading text-text-primary">{L('checksTitle')}</h2>
        <Row label={L('rules')}>
          <div className="flex flex-col gap-2" data-testid="purchasing-rules">
            {form.warehouse_rules.map((r, i) => (
              <div key={i} className="flex items-center gap-2">
                <select
                  aria-label={L('ruleSupplier')}
                  className={`${INPUT} min-w-0 flex-1`}
                  value={r.supplier_money_id}
                  onChange={(e) =>
                    set({
                      warehouse_rules: form.warehouse_rules.map((x, j) =>
                        j === i ? { ...x, supplier_money_id: e.target.value } : x,
                      ),
                    })
                  }
                >
                  <option value="">{L('pickSupplier')}</option>
                  {p.suppliers.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.label}
                    </option>
                  ))}
                </select>
                <select
                  aria-label={L('ruleWarehouse')}
                  className={`${INPUT} w-40`}
                  value={r.warehouse_id}
                  onChange={(e) =>
                    set({
                      warehouse_rules: form.warehouse_rules.map((x, j) =>
                        j === i ? { ...x, warehouse_id: e.target.value } : x,
                      ),
                    })
                  }
                >
                  <option value="">{L('pickWarehouse')}</option>
                  {p.warehouses.map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.label}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  aria-label={L('removeRule')}
                  className="text-text-secondary"
                  onClick={() => set({ warehouse_rules: form.warehouse_rules.filter((_, j) => j !== i) })}
                >
                  <X size={16} aria-hidden="true" />
                </button>
              </div>
            ))}
            <Button
              variant="secondary"
              className="w-fit"
              icon={<Plus size={16} aria-hidden="true" />}
              onClick={() =>
                set({ warehouse_rules: [...form.warehouse_rules, { supplier_money_id: '', warehouse_id: '' }] })
              }
            >
              {L('addRule')}
            </Button>
          </div>
        </Row>
        <Row label={L('priceDiff')} help={L('priceDiffHelp')}>
          <Pct
            value={form.price_diff_pct}
            onChange={(v) => set({ price_diff_pct: v })}
            label={L('priceDiff')}
            error={!pctOk(form.price_diff_pct) ? L('pctError') : null}
          />
        </Row>
        <Row label={L('qtyDiff')}>
          <Pct
            value={form.qty_diff_pct}
            onChange={(v) => set({ qty_diff_pct: v })}
            label={L('qtyDiff')}
            error={!pctOk(form.qty_diff_pct) ? L('pctError') : null}
          />
        </Row>
        <Row label={L('confirmRoles')}>
          <div className="flex flex-wrap gap-2" role="group" aria-label={L('confirmRoles')}>
            {ROLES.map((r) => {
              const on = form.confirm_roles.includes(r);
              return (
                <button
                  key={r}
                  type="button"
                  aria-pressed={on}
                  onClick={() =>
                    set({ confirm_roles: on ? form.confirm_roles.filter((x) => x !== r) : [...form.confirm_roles, r] })
                  }
                  className={`type-small inline-flex h-7 items-center gap-1 rounded-full px-3 ${
                    on
                      ? 'bg-brand-primary-600 text-text-on-primary'
                      : 'border border-border-default text-text-secondary'
                  }`}
                >
                  {t(`settings.purchasing.roles.${r}`)}
                  {on ? <X size={12} aria-hidden="true" /> : null}
                </button>
              );
            })}
            {form.confirm_roles.length === 0 ? (
              <span role="alert" className="type-caption w-full text-danger-600">
                {L('rolesError')}
              </span>
            ) : null}
          </div>
        </Row>
        <Row label={L('issueDate')} help={L('issueDateHelp')}>
          <div className="inline-flex rounded-md bg-bg-muted p-1" role="radiogroup" aria-label={L('issueDate')}>
            {(['supplier', 'approval'] as const).map((v) => (
              <button
                key={v}
                type="button"
                role="radio"
                aria-checked={form.issue_date === v}
                onClick={() => set({ issue_date: v })}
                className={`type-label h-8 rounded-sm px-3 ${
                  form.issue_date === v ? 'bg-bg-canvas text-text-primary shadow-sm' : 'text-text-secondary'
                }`}
              >
                {t(`settings.purchasing.issue.${v}`)}
              </button>
            ))}
          </div>
        </Row>
      </section>

      <Mappings suppliers={p.suppliers} />

      <div className="sticky bottom-0 z-10 -mx-4 flex gap-2 border-t border-border-default bg-bg-canvas px-4 py-4 md:-mx-6 md:px-6">
        <Button
          icon={<Check size={16} aria-hidden="true" />}
          disabled={!dirty || !valid || save.isPending}
          onClick={() => save.mutate(form)}
          data-testid="purchasing-save"
        >
          {t('settings.purchasing.save')}
        </Button>
        <Button variant="secondary" disabled={!dirty} onClick={() => setDraft(null)}>
          {t('common.cancel')}
        </Button>
      </div>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-1 items-center gap-2 md:grid-cols-[300px_minmax(0,1fr)] md:gap-6">
      <span className="type-body text-text-primary">{label}</span>
      <span className="type-small flex items-start gap-2 rounded-md bg-bg-muted px-3 py-2 text-text-secondary">
        <Lock size={14} aria-hidden="true" className="mt-0.5 shrink-0" />
        {value}
      </span>
    </div>
  );
}

function Row({ label, help, children }: { label: string; help?: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-1 items-start gap-2 md:grid-cols-[300px_minmax(0,1fr)] md:gap-6">
      <span className="flex flex-col pt-1">
        <span className="type-body text-text-primary">{label}</span>
        {help ? <span className="type-caption text-text-secondary">{help}</span> : null}
      </span>
      {children}
    </div>
  );
}

function Pct({
  value,
  onChange,
  label,
  error,
}: {
  value: string;
  onChange: (v: string) => void;
  label: string;
  error: string | null;
}) {
  return (
    <span className="flex flex-col gap-1">
      <span className="flex items-center gap-2">
        <input
          className={`${INPUT} !w-24`}
          inputMode="decimal"
          value={value}
          aria-label={label}
          aria-invalid={!!error}
          onChange={(e) => onChange(e.target.value)}
        />
        <span className="type-small text-text-secondary">%</span>
      </span>
      {error ? (
        <span role="alert" className="type-caption text-danger-600">
          {error}
        </span>
      ) : null}
    </span>
  );
}

function Mappings({ suppliers }: { suppliers: { id: string; label: string }[] }) {
  const { t } = useTranslation();
  const toasts = useToasts();
  const qc = useQueryClient();
  const [q, setQ] = useState('');
  const [supplier, setSupplier] = useState('');
  const [edit, setEdit] = useState<Mapping | null>(null);
  const [remove, setRemove] = useState<Mapping | null>(null);
  const params = new URLSearchParams();
  if (q.trim()) params.set('q', q.trim());
  if (supplier) params.set('supplier', supplier);
  const key = ['settings', 'purchasing', 'mappings', q.trim(), supplier] as const;
  const list = useQuery({
    queryKey: key,
    queryFn: () => api<{ items: Mapping[]; total: number }>('GET', `${URL}/mappings?${params.toString()}`),
  });
  const refresh = () => void qc.invalidateQueries({ queryKey: ['settings', 'purchasing', 'mappings'] });
  const fail = (e: unknown) =>
    toasts.error(
      t(`settings.purchasing.errors.${e instanceof ApiError ? e.detail.code : 'generic'}`, {
        defaultValue: t('mail.errors.generic'),
      }),
    );
  const del = useMutation({
    mutationFn: (m: Mapping) => api<null>('DELETE', `${URL}/mappings/${m.id}`, undefined, { global: false }),
    onSuccess: () => {
      setRemove(null);
      refresh();
      toasts.success(t('settings.purchasing.deleted'));
    },
    onError: fail,
  });
  const L = (k: string) => t(`settings.purchasing.${k}`);
  const items = list.data?.items ?? [];
  const csv = `${URL}/mappings.csv${supplier ? `?supplier=${supplier}` : ''}`;
  return (
    <section className="flex flex-col gap-3" data-testid="purchasing-mappings">
      <h2 className="type-heading text-text-primary">{L('mappingsTitle')}</h2>
      <div className="flex flex-wrap items-center gap-2">
        <label className="relative min-w-0 flex-1 basis-60 md:max-w-[320px]">
          <Search size={16} aria-hidden="true" className="absolute left-3 top-2.5 text-text-tertiary" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={L('mappingsSearch')}
            aria-label={L('mappingsSearch')}
            className="type-body h-9 w-full rounded-md bg-bg-muted pl-9 pr-3 placeholder:text-text-tertiary"
          />
        </label>
        <select
          aria-label={L('allSuppliers')}
          className={`${INPUT} w-48`}
          value={supplier}
          onChange={(e) => setSupplier(e.target.value)}
        >
          <option value="">{L('allSuppliers')}</option>
          {suppliers.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </select>
        <a
          href={csv}
          download
          className="type-label ml-auto inline-flex h-8 items-center gap-2 rounded-sm border border-border-strong px-3"
          data-testid="purchasing-export"
        >
          <Download size={16} aria-hidden="true" />
          {L('export')}
        </a>
      </div>
      <div className="overflow-x-auto rounded-md border border-border-default">
        <table className="type-small w-full min-w-[860px] text-left text-text-primary">
          <thead className="bg-bg-subtle text-text-secondary">
            <tr>
              {(['supplier', 'code', 'article', 'factor', 'by', 'date', 'uses'] as const).map((c) => (
                <th key={c} className={`px-3 py-2 font-normal ${c === 'uses' ? 'text-right' : ''}`}>
                  {t(`settings.purchasing.cols.${c}`)}
                </th>
              ))}
              <th className="w-10">
                <span className="sr-only">{L('delete')}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && !list.isLoading ? (
              <tr>
                <td colSpan={8} className="px-3 py-6 text-center text-text-secondary">
                  {L('mappingsEmpty')}
                </td>
              </tr>
            ) : null}
            {items.map((m) => (
              <tr
                key={m.id}
                className="cursor-pointer border-t border-border-default hover:bg-bg-subtle"
                tabIndex={0}
                onClick={() => setEdit(m)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') setEdit(m);
                }}
                data-testid={`mapping-${m.code}`}
              >
                <td className="px-3 py-2">{m.supplier_name ?? '–'}</td>
                <td className="px-3 py-2">{m.code}</td>
                <td className="px-3 py-2">{m.article_name ?? m.article_id}</td>
                <td className="px-3 py-2">1 : {m.unit_factor.replace('.', ',')}</td>
                <td className="px-3 py-2">{m.confirmed_by ?? '–'}</td>
                <td className="px-3 py-2">{day(m.confirmed_at)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{m.uses_count}×</td>
                <td className="px-2">
                  <button
                    type="button"
                    aria-label={L('delete')}
                    className="text-text-secondary hover:text-danger-600"
                    onClick={(e) => {
                      e.stopPropagation();
                      setRemove(m);
                    }}
                  >
                    <Trash2 size={16} aria-hidden="true" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="type-caption text-text-secondary">{L('mappingsHelp')}</p>
      {edit ? (
        <EditMapping
          m={edit}
          onClose={() => setEdit(null)}
          onSaved={() => {
            setEdit(null);
            refresh();
            toasts.success(t('settings.saved'));
          }}
          onError={fail}
        />
      ) : null}
      {remove ? (
        <Dialog
          title={L('deleteTitle')}
          width={440}
          onClose={() => setRemove(null)}
          footer={
            <>
              <Button variant="secondary" onClick={() => setRemove(null)}>
                {t('common.cancel')}
              </Button>
              <Button onClick={() => del.mutate(remove)} disabled={del.isPending} data-testid="mapping-delete-confirm">
                {L('delete')}
              </Button>
            </>
          }
        >
          <p className="type-body text-text-primary">
            {t('settings.purchasing.deleteText', { code: remove.code, supplier: remove.supplier_name ?? '' })}
          </p>
        </Dialog>
      ) : null}
    </section>
  );
}

function EditMapping({
  m,
  onClose,
  onSaved,
  onError,
}: {
  m: Mapping;
  onClose: () => void;
  onSaved: () => void;
  onError: (e: unknown) => void;
}) {
  const { t } = useTranslation();
  const [factor, setFactor] = useState(m.unit_factor.replace('.', ','));
  const ok = /^\d{1,12}([.,]\d{1,6})?$/.test(factor) && !/^0+([.,]0*)?$/.test(factor);
  const save = useMutation({
    mutationFn: () =>
      api<Mapping>('PATCH', `${URL}/mappings/${m.id}`, { unit_factor: factor.replace(',', '.') }, { global: false }),
    onSuccess: onSaved,
    onError,
  });
  return (
    <Dialog
      title={t('settings.purchasing.editTitle', { code: m.code })}
      width={480}
      onClose={onClose}
      onSubmit={() => ok && save.mutate()}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" disabled={!ok || save.isPending}>
            {t('settings.purchasing.save')}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <p className="type-small text-text-secondary">
          {m.supplier_name} · {m.article_name ?? m.article_id}
        </p>
        <label className="type-label flex flex-col gap-1">
          {t('settings.purchasing.cols.factor')}
          <input
            className={INPUT}
            value={factor}
            inputMode="decimal"
            aria-invalid={!ok}
            onChange={(e) => setFactor(e.target.value)}
            data-autofocus
          />
          <span className="type-caption text-text-secondary">{t('settings.purchasing.factorHelp')}</span>
        </label>
      </div>
    </Dialog>
  );
}
