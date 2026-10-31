import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Building2, CircleAlert, Link2, Search, X } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { Banner } from '../../components/Banner';
import { Button } from '../../components/Button';
import { useToast } from '../../components/toastContext';
import { ApiError } from '../../lib/api';
import {
  cardKey,
  customerKey,
  day,
  fetchCard,
  fetchCustomer,
  linkEmail,
  money,
  searchCompanies,
  type CompanyBrief,
  type CustomerMatch,
} from './moneyApi';

type Props = { messageId: string; readOnly: boolean; mobile: boolean; onClose: () => void };

/**
 * W3b Zákazník (desktop panel 380 px) / M10 (mobile, full screen) — Phase 3c. `CustomerCard` of the company that the
 * sender matches in the Money read cache; not matched → „Priradiť k firme“. „Založiť firmu v Money“ is a write and
 * comes in Phase 4 (disabled here). Read-only towards Money.
 */
export function CustomerPanel({ messageId, readOnly, mobile, onClose }: Props) {
  const { t } = useTranslation();
  const match = useQuery({ queryKey: customerKey(messageId), queryFn: () => fetchCustomer(messageId) });
  return (
    <aside
      aria-label={t('money.customer.title')}
      data-testid="customer-panel"
      className={`fixed z-30 flex flex-col overflow-y-auto border-border-default bg-bg-canvas shadow-lg ${
        mobile ? 'inset-0' : 'top-0 right-0 bottom-0 w-[380px] border-l'
      }`}
    >
      <header className="sticky top-0 flex h-12 shrink-0 items-center gap-2 border-b border-border-default bg-bg-canvas px-3">
        <Building2 size={18} aria-hidden="true" className="text-text-secondary" />
        <h2 className="type-heading min-w-0 flex-1 truncate text-text-primary">{t('money.customer.title')}</h2>
        <button
          type="button"
          onClick={onClose}
          aria-label={t('money.customer.close')}
          className="flex size-9 items-center justify-center rounded-sm text-text-secondary hover:bg-bg-subtle"
        >
          <X size={18} aria-hidden="true" />
        </button>
      </header>
      <div className="flex flex-col gap-4 p-4">
        {match.isPending ? <Skeleton /> : null}
        {match.isError ? <Banner kind="warning" message={t('money.customer.error')} /> : null}
        {match.data ? <Matched match={match.data} messageId={messageId} readOnly={readOnly} /> : null}
      </div>
    </aside>
  );
}

function Skeleton() {
  const { t } = useTranslation();
  return (
    <div aria-busy="true" aria-label={t('money.customer.loading')} className="flex flex-col gap-2">
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-6 animate-pulse rounded-sm bg-bg-muted" />
      ))}
    </div>
  );
}

function Matched({ match, messageId, readOnly }: { match: CustomerMatch; messageId: string; readOnly: boolean }) {
  const { t } = useTranslation();
  if (!match.email) return <p className="type-small text-text-secondary">{t('money.customer.internal')}</p>;
  if (!match.company) {
    return <NotMatched match={match} messageId={messageId} readOnly={readOnly} />;
  }
  return (
    <>
      <p className="type-small text-text-secondary" data-testid="match-method">
        {t(`money.customer.methods.${match.method ?? 'company_email'}`, { email: match.email })}
      </p>
      {match.needs_confirmation ? (
        <ConfirmDomain email={match.email} company={match.company} messageId={messageId} readOnly={readOnly} />
      ) : null}
      <CustomerCard company={match.company} />
    </>
  );
}

function ConfirmDomain({
  email,
  company,
  messageId,
  readOnly,
}: {
  email: string;
  company: CompanyBrief;
  messageId: string;
  readOnly: boolean;
}) {
  const { t } = useTranslation();
  const link = useLink(messageId);
  return (
    <div className="flex flex-col gap-2 rounded-md border border-warning-600 bg-warning-50 p-3">
      <p className="type-small text-text-primary">{t('money.customer.confirmDomain', { email, name: company.name })}</p>
      <div>
        <Button
          type="button"
          variant="secondary"
          disabled={readOnly || link.isPending}
          onClick={() => link.mutate({ email, id: company.money_id })}
          icon={<Link2 size={16} aria-hidden="true" />}
        >
          {t('money.customer.confirm')}
        </Button>
      </div>
    </div>
  );
}

function useLink(messageId: string) {
  const { t } = useTranslation();
  const toast = useToast();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ email, id }: { email: string; id: string }) => linkEmail(email, id),
    onSuccess: (out) => {
      qc.setQueryData(customerKey(messageId), out);
      toast({ message: t('money.customer.linked', { name: out.company?.name ?? '' }) });
    },
    onError: (error) => {
      const code = error instanceof ApiError ? error.detail.code : 'generic';
      toast({ message: t(`money.customer.errors.${code}`, { defaultValue: t('mail.errors.generic') }) });
    },
  });
}

function NotMatched({ match, messageId, readOnly }: { match: CustomerMatch; messageId: string; readOnly: boolean }) {
  const { t } = useTranslation();
  const [q, setQ] = useState('');
  const term = q.trim();
  const found = useQuery({
    queryKey: ['money', 'search', term],
    queryFn: () => searchCompanies(term),
    enabled: term.length >= 2,
  });
  const link = useLink(messageId);
  const email = match.email ?? '';
  const pick = (c: CompanyBrief) => link.mutate({ email, id: c.money_id });
  const options = term.length >= 2 ? (found.data ?? []) : match.candidates;
  return (
    <div className="flex flex-col gap-3" data-testid="customer-not-matched">
      <p className="type-body text-text-primary">
        {match.candidates.length > 0
          ? t('money.customer.ambiguous', { email })
          : t('money.customer.notMatched', { email })}
      </p>
      <label className="flex flex-col gap-1">
        <span className="type-label text-text-secondary">{t('money.customer.assign')}</span>
        <span className="relative">
          <Search
            size={16}
            aria-hidden="true"
            className="pointer-events-none absolute top-1/2 left-2 -translate-y-1/2 text-text-tertiary"
          />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t('money.customer.searchPlaceholder')}
            disabled={readOnly}
            className="type-body h-9 w-full rounded-sm border border-border-default bg-bg-canvas pr-2 pl-8"
          />
        </span>
      </label>
      {options.length > 0 ? (
        <ul className="flex flex-col divide-y divide-border-default rounded-md border border-border-default">
          {options.map((c) => (
            <li key={c.money_id} className="flex items-center gap-2 p-2">
              <span className="min-w-0 flex-1">
                <span className="type-label block truncate text-text-primary">{c.name}</span>
                <span className="type-small text-text-secondary">
                  {[c.ico ? t('money.customer.ico', { ico: c.ico }) : null, c.code].filter(Boolean).join(' · ')}
                </span>
              </span>
              <Button
                type="button"
                variant="secondary"
                disabled={readOnly || link.isPending}
                onClick={() => pick(c)}
                aria-label={t('money.customer.assignTo', { name: c.name })}
              >
                {t('money.customer.assignShort')}
              </Button>
            </li>
          ))}
        </ul>
      ) : term.length >= 2 && found.data ? (
        <p className="type-small text-text-secondary">{t('money.customer.noResults')}</p>
      ) : null}
      <div>
        <Button type="button" variant="secondary" disabled title={t('money.customer.createLater')}>
          {t('money.customer.create')}
        </Button>
        <p className="type-caption mt-1 text-text-secondary">{t('money.customer.createLater')}</p>
      </div>
    </div>
  );
}

function Section({ title, error, children }: { title: string; error: string | null; children: ReactNode }) {
  const { t } = useTranslation();
  return (
    <section className="flex flex-col gap-1">
      <h3 className="type-label text-text-secondary">{title}</h3>
      {error ? (
        <p className="type-small inline-flex items-center gap-1 text-warning-700">
          <CircleAlert size={14} aria-hidden="true" />
          {t(`money.customer.partErrors.${error}`, { defaultValue: t('money.customer.partErrors.money_unavailable') })}
        </p>
      ) : (
        children
      )}
    </section>
  );
}

/** UX_SPEC `CustomerCard`: header, KPIs (otvorené faktúry, po splatnosti), objednávky, dodacie listy, aktivity, kontakty. */
export function CustomerCard({ company }: { company: CompanyBrief }) {
  const { t } = useTranslation();
  const card = useQuery({ queryKey: cardKey(company.money_id), queryFn: () => fetchCard(company.money_id) });
  const c = card.data;
  const r = c?.receivables;
  return (
    <div className="flex flex-col gap-4" data-testid="customer-card">
      <header className="flex flex-col gap-0.5">
        <h3 className="type-heading text-text-primary">{company.name}</h3>
        <p className="type-small text-text-secondary">
          {[
            company.ico ? t('money.customer.ico', { ico: company.ico }) : null,
            company.icdph ? t('money.customer.icdph', { icdph: company.icdph }) : null,
            company.code,
          ]
            .filter(Boolean)
            .join(' · ')}
        </p>
        <p className="type-small text-text-secondary">
          {[
            company.discount_pct && Number(company.discount_pct) !== 0
              ? t('money.customer.discount', { pct: company.discount_pct.replace('.', ',') })
              : null,
            company.due_days != null ? t('money.customer.due', { count: company.due_days }) : null,
          ]
            .filter(Boolean)
            .join(' · ')}
        </p>
      </header>
      {card.isPending ? <Skeleton /> : null}
      {card.isError ? <Banner kind="warning" message={t('money.customer.error')} /> : null}
      {c && r ? (
        <>
          <Section title={t('money.customer.receivables')} error={r.error}>
            <div className="grid grid-cols-2 gap-2">
              <Kpi label={t('money.customer.open', { count: r.open_count })} value={money(r.open_total)} />
              <Kpi
                label={t('money.customer.overdue', { count: r.overdue_count })}
                value={money(r.overdue_total)}
                tone={r.overdue_count > 0 ? 'warning' : undefined}
                sub={
                  r.oldest_overdue_days != null ? t('money.customer.oldest', { count: r.oldest_overdue_days }) : null
                }
              />
            </div>
            <Rows
              rows={r.items.map((i) => ({
                id: i.id,
                left: i.number,
                mid: t('money.customer.dueOn', { date: day(i.due_on) }),
                right: money(i.remaining),
              }))}
              empty={t('money.customer.noOpen')}
            />
          </Section>
          <Section title={t('money.customer.orders')} error={c.orders.error}>
            <Rows
              rows={c.orders.items.map((o) => ({
                id: o.id,
                left: o.number,
                mid: [day(o.issued_on), o.reference].filter(Boolean).join(' · '),
                right: money(o.total),
              }))}
              empty={t('money.customer.none')}
            />
          </Section>
          <Section title={t('money.customer.deliveries')} error={c.deliveries.error}>
            <Rows
              rows={c.deliveries.items.map((d) => ({
                id: d.id,
                left: d.number,
                mid: [day(d.issued_on), d.transport].filter(Boolean).join(' · '),
                right: money(d.total),
              }))}
              empty={t('money.customer.none')}
            />
          </Section>
          <Section title={t('money.customer.activities')} error={c.activities.error}>
            <Rows
              rows={c.activities.items.map((a) => ({
                id: a.id,
                left: day(a.started_at),
                mid: a.description ?? '',
                right: '',
              }))}
              empty={t('money.customer.none')}
            />
          </Section>
          <Section title={t('money.customer.contacts')} error={null}>
            <Rows
              rows={c.persons.map((p) => ({
                id: p.money_id,
                left: p.name ?? '–',
                mid: [p.function, p.email].filter(Boolean).join(' · '),
                right: '',
              }))}
              empty={t('money.customer.none')}
            />
          </Section>
        </>
      ) : null}
    </div>
  );
}

function Kpi({ label, value, sub, tone }: { label: string; value: string; sub?: string | null; tone?: 'warning' }) {
  return (
    <div
      className={`flex flex-col rounded-md border p-2 ${
        tone === 'warning' ? 'border-warning-600 bg-warning-50' : 'border-border-default'
      }`}
    >
      <span className="type-small text-text-secondary">{label}</span>
      <span className="type-heading text-text-primary">{value}</span>
      {sub ? <span className="type-caption text-text-secondary">{sub}</span> : null}
    </div>
  );
}

function Rows({ rows, empty }: { rows: { id: string; left: string; mid: string; right: string }[]; empty: string }) {
  if (rows.length === 0) return <p className="type-small text-text-secondary">{empty}</p>;
  return (
    <ul className="flex flex-col divide-y divide-border-default">
      {rows.map((row) => (
        <li key={row.id} className="type-small flex items-baseline gap-2 py-1 text-text-primary">
          <span className="shrink-0 font-medium">{row.left}</span>
          <span className="min-w-0 flex-1 truncate text-text-secondary">{row.mid}</span>
          {row.right ? <span className="shrink-0 tabular-nums">{row.right}</span> : null}
        </li>
      ))}
    </ul>
  );
}
