import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  Building2,
  CircleAlert,
  CircleCheck,
  ExternalLink,
  FileText,
  Link2,
  Mail,
  Phone,
  Search,
  Send,
  Sparkles,
  X,
} from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

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
  type CompanyCard,
  type CustomerMatch,
} from './moneyApi';

type Props = { messageId: string; readOnly: boolean; mobile: boolean; onClose: () => void };
type MobileTab = 'overview' | 'documents' | 'contacts';

/**
 * W3b (desktop: right column 380 px next to the reading pane, tabs „Asistent | Zákazník“ — the assistant comes in
 * Phase 5) / M10 (mobile: full screen, tabs Prehľad · Doklady · Kontakty, bottom bar Volať + Napísať). Phase 3c,
 * Figma 36:31480, 36:31615, 84:3510. Read-only towards Money; „Založiť firmu v Money“ comes in Phase 4.
 */
export function CustomerPanel({ messageId, readOnly, mobile, onClose }: Props) {
  const { t } = useTranslation();
  const match = useQuery({ queryKey: customerKey(messageId), queryFn: () => fetchCustomer(messageId) });
  const [tab, setTab] = useState<MobileTab>('overview');
  const company = match.data?.company ?? null;
  const card = useQuery({
    queryKey: cardKey(company?.money_id ?? ''),
    queryFn: () => fetchCard(company?.money_id ?? ''),
    enabled: Boolean(company),
  });

  const body = (
    <div className="flex flex-col gap-4 p-4">
      {match.isPending ? <Skeleton /> : null}
      {match.isError ? <Banner kind="warning" message={t('money.customer.error')} /> : null}
      {match.data ? (
        <Matched
          match={match.data}
          messageId={messageId}
          readOnly={readOnly}
          card={card.data}
          cardPending={card.isPending}
          cardError={card.isError}
          only={mobile ? tab : null}
        />
      ) : null}
    </div>
  );

  if (mobile) {
    return (
      <aside
        aria-label={t('money.customer.title')}
        data-testid="customer-panel"
        className="fixed inset-0 z-30 flex flex-col bg-bg-canvas"
      >
        <header className="flex h-12 shrink-0 items-center gap-1 border-b border-border-default px-1">
          <button
            type="button"
            onClick={onClose}
            aria-label={t('money.customer.close')}
            className="flex size-11 items-center justify-center rounded-sm text-text-primary hover:bg-bg-subtle"
          >
            <ArrowLeft size={22} aria-hidden="true" />
          </button>
          <h2 className="type-heading min-w-0 flex-1 truncate text-text-primary">
            {company?.name ?? t('money.customer.title')}
          </h2>
        </header>
        {company ? (
          <div
            role="tablist"
            aria-label={t('money.customer.title')}
            className="flex shrink-0 border-b border-border-default"
          >
            {(['overview', 'documents', 'contacts'] as const).map((id) => (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={tab === id}
                onClick={() => setTab(id)}
                className={`type-label h-11 flex-1 border-b-2 ${
                  tab === id
                    ? 'border-brand-primary-600 text-brand-primary-700'
                    : 'border-transparent text-text-secondary'
                }`}
              >
                {t(`money.customer.tabs.${id}`)}
              </button>
            ))}
          </div>
        ) : null}
        <div className="min-h-0 flex-1 overflow-y-auto">{body}</div>
        {company ? <MobileBar match={match.data} card={card.data} /> : null}
      </aside>
    );
  }

  return (
    <aside
      aria-label={t('money.customer.panel')}
      data-testid="customer-panel"
      className="flex w-[380px] shrink-0 flex-col border-l border-border-default bg-bg-canvas"
    >
      <header className="flex h-12 shrink-0 items-center gap-1 border-b border-border-default px-2">
        <div role="tablist" aria-label={t('money.customer.panel')} className="flex min-w-0 flex-1 gap-1">
          <button
            type="button"
            role="tab"
            aria-selected={false}
            disabled
            title={t('money.customer.assistantLater')}
            className="type-label inline-flex h-9 items-center gap-1 rounded-sm px-2 text-text-tertiary"
          >
            <Sparkles size={16} aria-hidden="true" />
            {t('money.customer.assistant')}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected
            className="type-label inline-flex h-9 items-center gap-1 rounded-sm bg-brand-primary-50 px-2 text-brand-primary-700"
          >
            <Building2 size={16} aria-hidden="true" />
            {t('money.customer.title')}
          </button>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label={t('money.customer.close')}
          className="flex size-9 items-center justify-center rounded-sm text-text-secondary hover:bg-bg-subtle"
        >
          <X size={18} aria-hidden="true" />
        </button>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto">{body}</div>
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

function Matched({
  match,
  messageId,
  readOnly,
  card,
  cardPending,
  cardError,
  only,
}: {
  match: CustomerMatch;
  messageId: string;
  readOnly: boolean;
  card: CompanyCard | undefined;
  cardPending: boolean;
  cardError: boolean;
  only: MobileTab | null;
}) {
  const { t } = useTranslation();
  if (!match.email) return <p className="type-small text-text-secondary">{t('money.customer.internal')}</p>;
  if (!match.company) return <NotMatched match={match} messageId={messageId} readOnly={readOnly} />;
  return (
    <>
      {match.needs_confirmation ? (
        <ConfirmDomain email={match.email} company={match.company} messageId={messageId} readOnly={readOnly} />
      ) : null}
      <CustomerCard
        company={match.company}
        method={t(`money.customer.methods.${match.method ?? 'company_email'}`, { email: match.email })}
        email={match.email}
        card={card}
        pending={cardPending}
        error={cardError}
        only={only}
      />
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
              <Initials name={c.name} />
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
                onClick={() => link.mutate({ email, id: c.money_id })}
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

function Initials({ name, size = 'size-9' }: { name: string; size?: string }) {
  const letters = name
    .replace(/\b(s\.r\.o\.|a\.s\.|spol\.)/gi, '')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? '')
    .join('');
  return (
    <span
      aria-hidden="true"
      className={`type-label flex ${size} shrink-0 items-center justify-center rounded-full bg-brand-primary-100 text-brand-primary-700`}
    >
      {letters || '?'}
    </span>
  );
}

function Chip({ children, tone }: { children: ReactNode; tone?: 'success' }) {
  return (
    <span
      className={`type-small inline-flex h-6 items-center gap-1 rounded-full border px-2 ${
        tone === 'success'
          ? 'border-success-600 bg-success-50 text-success-700'
          : 'border-border-default bg-bg-subtle text-text-primary'
      }`}
    >
      {children}
    </span>
  );
}

function Section({
  title,
  error,
  action,
  children,
}: {
  title: string;
  error: string | null;
  action?: ReactNode;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <section className="flex flex-col gap-1">
      <div className="flex items-center gap-2">
        <h3 className="type-micro min-w-0 flex-1 tracking-wide text-text-secondary uppercase">{title}</h3>
        {action}
      </div>
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

function daysOverdue(due: string | null): number {
  if (!due) return 0;
  const [y, m, d] = due.slice(0, 10).split('-').map(Number);
  const dueDay = Date.UTC(y ?? 1970, (m ?? 1) - 1, d ?? 1);
  const now = new Date();
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.max(0, Math.round((today - dueDay) / 86_400_000));
}

/** UX_SPEC `CustomerCard` laid out like Figma W3b 36:31480; `only` limits it to one M10 tab on mobile. */
export function CustomerCard({
  company,
  method,
  email,
  card,
  pending,
  error,
  only = null,
}: {
  company: CompanyBrief;
  method: string;
  email: string;
  card: CompanyCard | undefined;
  pending: boolean;
  error: boolean;
  only?: MobileTab | null;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const r = card?.receivables;
  const show = (tab: MobileTab) => only === null || only === tab;
  return (
    <div className="flex flex-col gap-4" data-testid="customer-card">
      {show('overview') ? (
        <header className="flex flex-col gap-2">
          <div className="flex items-start gap-3">
            <Initials name={company.name} size="size-11" />
            <div className="min-w-0 flex-1">
              <h3 className="type-heading text-text-primary">{company.name}</h3>
              <p className="type-small text-text-secondary">
                {[
                  company.ico ? t('money.customer.ico', { ico: company.ico }) : null,
                  company.icdph ? t('money.customer.icdph', { icdph: company.icdph }) : null,
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {company.discount_pct && Number(company.discount_pct) !== 0 ? (
              <Chip>{t('money.customer.discount', { pct: company.discount_pct.replace('.', ',') })}</Chip>
            ) : null}
            {company.due_days != null ? <Chip>{t('money.customer.due', { count: company.due_days })}</Chip> : null}
            <Chip tone="success">
              <CircleCheck size={14} aria-hidden="true" />
              {t('money.customer.inMoney')}
            </Chip>
          </div>
          <p className="type-caption text-text-secondary" data-testid="match-method">
            {method}
          </p>
        </header>
      ) : null}
      {pending ? <Skeleton /> : null}
      {error ? <Banner kind="warning" message={t('money.customer.error')} /> : null}
      {card && r ? (
        <>
          {show('overview') ? (
            r.error ? (
              <Section title={t('money.customer.receivables')} error={r.error}>
                {null}
              </Section>
            ) : (
              <div className="grid grid-cols-2 gap-2">
                <Kpi
                  label={t('money.customer.openTitle')}
                  value={money(r.open_total)}
                  sub={t('money.customer.open', { count: r.open_count })}
                  edge="border-l-brand-primary-600"
                />
                <Kpi
                  label={t('money.customer.overdueTitle')}
                  value={money(r.overdue_total)}
                  sub={
                    r.oldest_overdue_days != null
                      ? t('money.customer.days', { count: r.oldest_overdue_days })
                      : t('money.customer.open', { count: r.overdue_count })
                  }
                  edge={r.overdue_count > 0 ? 'border-l-danger-600' : 'border-l-border-strong'}
                />
              </div>
            )
          ) : null}
          {show('documents') ? (
            <>
              <Section
                title={t('money.customer.receivables')}
                error={r.error}
                action={
                  <button
                    type="button"
                    disabled
                    title={t('money.customer.later3e')}
                    className="type-small text-text-tertiary"
                  >
                    {t('money.customer.statement')}
                  </button>
                }
              >
                {r.items.length === 0 ? (
                  <p className="type-small text-text-secondary">{t('money.customer.noOpen')}</p>
                ) : (
                  <ul className="flex flex-col divide-y divide-border-default">
                    {r.items.map((i) => {
                      const late = daysOverdue(i.due_on);
                      return (
                        <li key={i.id} className="flex items-center gap-2 py-1.5">
                          <span className="min-w-0 flex-1">
                            <span className="type-label block text-text-primary">{i.number}</span>
                            <span className={`type-small ${late > 0 ? 'text-danger-600' : 'text-text-secondary'}`}>
                              {t('money.customer.dueOn', { date: day(i.due_on) })}
                              {late > 0 ? ` · ${t('money.customer.lateDays', { count: late })}` : ''}
                            </span>
                          </span>
                          <span className="type-small shrink-0 text-text-primary tabular-nums">
                            {money(i.remaining)}
                          </span>
                          <Button
                            type="button"
                            variant="secondary"
                            disabled
                            title={t('money.customer.later3d')}
                            icon={<Send size={14} aria-hidden="true" />}
                          >
                            {t('money.customer.send')}
                          </Button>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </Section>
              <Section title={t('money.customer.orders')} error={card.orders.error}>
                <Rows
                  rows={card.orders.items.map((o) => ({
                    id: o.id,
                    left: o.number,
                    mid: [day(o.issued_on), o.reference].filter(Boolean).join(' · '),
                    right: money(o.total),
                  }))}
                  empty={t('money.customer.none')}
                />
              </Section>
              <Section title={t('money.customer.deliveries')} error={card.deliveries.error}>
                <Rows
                  rows={card.deliveries.items.map((d) => ({
                    id: d.id,
                    left: d.number,
                    mid: [day(d.issued_on), d.transport].filter(Boolean).join(' · '),
                    right: money(d.total),
                  }))}
                  empty={t('money.customer.none')}
                />
              </Section>
            </>
          ) : null}
          {show('contacts') ? (
            <>
              <Section title={t('money.customer.activities')} error={card.activities.error}>
                <Rows
                  rows={card.activities.items.map((a) => ({
                    id: a.id,
                    left: a.description ?? '–',
                    mid: day(a.started_at),
                    right: '',
                  }))}
                  empty={t('money.customer.none')}
                />
              </Section>
              <Section title={t('money.customer.contacts')} error={null}>
                {card.persons.length === 0 ? (
                  <p className="type-small text-text-secondary">{t('money.customer.none')}</p>
                ) : (
                  <ul className="flex flex-col gap-2">
                    {card.persons.map((p) => (
                      <li key={p.money_id} className="flex items-center gap-2">
                        <Initials name={p.name ?? '?'} size="size-8" />
                        <span className="min-w-0 flex-1">
                          <span className="type-label block truncate text-text-primary">{p.name ?? '–'}</span>
                          <span className="type-small block truncate text-text-secondary">
                            {[p.function, p.email, p.phone].filter(Boolean).join(' · ')}
                          </span>
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </Section>
            </>
          ) : null}
        </>
      ) : null}
      {only === null ? (
        <div className="grid grid-cols-2 gap-2 border-t border-border-default pt-3">
          <Button
            type="button"
            icon={<Mail size={16} aria-hidden="true" />}
            onClick={() => navigate(`/compose?to=${encodeURIComponent(email)}`)}
          >
            {t('money.customer.write')}
          </Button>
          <Button
            type="button"
            variant="secondary"
            disabled
            title={t('money.customer.later3e')}
            icon={<FileText size={16} aria-hidden="true" />}
          >
            {t('money.customer.statementLong')}
          </Button>
          <Button type="button" variant="secondary" disabled title={t('money.customer.laterOffer')}>
            {t('money.customer.offer')}
          </Button>
          <Button
            type="button"
            variant="secondary"
            disabled
            title={t('money.customer.openInMoneyLater')}
            icon={<ExternalLink size={16} aria-hidden="true" />}
          >
            {t('money.customer.openInMoney')}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function MobileBar({ match, card }: { match: CustomerMatch | undefined; card: CompanyCard | undefined }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const phone = card?.persons.find((p) => p.phone)?.phone ?? null;
  return (
    <div className="grid shrink-0 grid-cols-2 gap-2 border-t border-border-default p-3">
      {phone ? (
        <a
          href={`tel:${phone.replace(/\s+/g, '')}`}
          className="type-label inline-flex h-10 items-center justify-center gap-1 rounded-sm border border-border-strong text-text-primary"
        >
          <Phone size={16} aria-hidden="true" />
          {t('money.customer.call')}
        </a>
      ) : (
        <Button type="button" variant="secondary" disabled icon={<Phone size={16} aria-hidden="true" />}>
          {t('money.customer.call')}
        </Button>
      )}
      <Button
        type="button"
        icon={<Mail size={16} aria-hidden="true" />}
        onClick={() => navigate(`/compose?to=${encodeURIComponent(match?.email ?? '')}`)}
      >
        {t('money.customer.write')}
      </Button>
    </div>
  );
}

function Kpi({ label, value, sub, edge }: { label: string; value: string; sub?: string | null; edge: string }) {
  return (
    <div className={`flex flex-col rounded-md border border-l-4 border-border-default p-2 ${edge}`}>
      <span className="type-small text-text-secondary">{label}</span>
      <span className="type-heading text-text-primary tabular-nums">{value}</span>
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
