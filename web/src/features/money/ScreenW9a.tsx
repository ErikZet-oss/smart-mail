import { useQuery } from '@tanstack/react-query';
import {
  ArrowDownLeft,
  ArrowLeft,
  ArrowUpRight,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  FileText,
  Mail,
  ReceiptText,
  ShoppingCart,
} from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, Navigate, useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { Banner } from '../../components/Banner';
import { Button } from '../../components/Button';
import { Menu } from '../../components/Menu';
import { AppShell } from '../../components/shell/AppShell';
import { fetchMe } from '../auth/authApi';
import { useFeaturesState } from '../system/features';
import { cardKey, day, fetchCard, fetchCompanyMail, money, type CompanyCard } from './moneyApi';

type Tab = 'overview' | 'emails' | 'documents' | 'contacts' | 'activities';
const TABS: Tab[] = ['overview', 'emails', 'documents', 'contacts', 'activities'];

function initials(name: string): string {
  return (
    name
      .replace(/\b(s\.r\.o\.|a\.s\.|spol\.)/gi, '')
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0]?.toUpperCase() ?? '')
      .join('') || '?'
  );
}

/**
 * W9a Zákazník 360 — `/contacts/company/:moneyId` (Phase 3g, Figma 60:48893): breadcrumb, header with chips,
 * tabs Prehľad · E-maily · Doklady · Kontakty · Aktivity. Read-only towards Money. Credit bar, 12-month turnover,
 * the AI relationship summary and W9b Objednávky come in later phases (hidden, never shown as 0).
 */
export function ScreenW9a() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { moneyId = '' } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = (TABS.includes(params.get('tab') as Tab) ? params.get('tab') : 'overview') as Tab;
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  const features = useFeaturesState();
  const me = useQuery({ queryKey: ['me'], queryFn: fetchMe, retry: false });
  const card = useQuery({
    queryKey: [...cardKey(moneyId), 50],
    queryFn: () => fetchCard(moneyId, 50),
    enabled: features.money && Boolean(moneyId),
    retry: false,
  });
  const mail = useQuery({
    queryKey: ['money', 'company-mail', moneyId],
    queryFn: () => fetchCompanyMail(moneyId),
    enabled: features.money && Boolean(moneyId),
  });
  if (features.loaded && !features.money) return <Navigate to="/404" replace />;
  const c = card.data;
  const company = c?.company;
  const readOnly = !me.data?.person || Boolean(me.data.read_only);
  const contact = company?.email ?? c?.persons.find((p) => p.email)?.email ?? null;
  const counts: Partial<Record<Tab, number>> = { emails: mail.data?.length, contacts: c?.persons.length };

  return (
    <AppShell section="contacts">
      <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto bg-bg-canvas" data-testid="screen-w9a">
        <header className="flex flex-col gap-3 border-b border-border-default px-4 pt-3 md:px-6">
          <nav
            aria-label={t('money.c360.breadcrumb')}
            className="type-small flex items-center gap-1 text-text-secondary"
          >
            <button
              type="button"
              onClick={() => navigate(-1)}
              aria-label={t('system.back')}
              className="flex size-7 items-center justify-center rounded-sm hover:bg-bg-subtle"
            >
              <ArrowLeft size={16} aria-hidden="true" />
            </button>
            <Link to="/contacts/personal" className="hover:underline">
              {t('rail.contacts')}
            </Link>
            <ChevronRight size={14} aria-hidden="true" />
            <span>{t('money.c360.moneyBook')}</span>
          </nav>
          <div className="flex flex-wrap items-start gap-3">
            <span
              aria-hidden="true"
              className="type-heading flex size-12 shrink-0 items-center justify-center rounded-full bg-brand-primary-100 text-brand-primary-700"
            >
              {initials(company?.name ?? '')}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="type-title truncate text-text-primary">{company?.name ?? t('money.c360.title')}</h1>
                {company ? (
                  <span className="type-small inline-flex h-6 items-center gap-1 rounded-full border border-success-600 bg-success-50 px-2 text-success-700">
                    <CircleCheck size={14} aria-hidden="true" />
                    {t('money.customer.inMoney')}
                  </span>
                ) : null}
              </div>
              {company ? (
                <>
                  <p className="type-small text-text-secondary">
                    {[
                      company.ico ? t('money.customer.ico', { ico: company.ico }) : null,
                      company.dic ? t('money.c360.dic', { dic: company.dic }) : null,
                      company.icdph ? t('money.customer.icdph', { icdph: company.icdph }) : null,
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </p>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {company.discount_pct && Number(company.discount_pct) !== 0 ? (
                      <Chip>{t('money.customer.discount', { pct: company.discount_pct.replace('.', ',') })}</Chip>
                    ) : null}
                    {company.due_days != null ? (
                      <Chip>{t('money.customer.due', { count: company.due_days })}</Chip>
                    ) : null}
                  </div>
                </>
              ) : null}
            </div>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                disabled={!contact || readOnly}
                onClick={() => navigate(`/compose?to=${encodeURIComponent(contact ?? '')}`)}
                icon={<Mail size={16} aria-hidden="true" />}
              >
                {t('money.customer.write')}
              </Button>
              <Button
                type="button"
                variant="secondary"
                aria-haspopup="menu"
                onClick={(e) => {
                  const r = e.currentTarget.getBoundingClientRect();
                  setMenu({ x: r.right - 260, y: r.bottom + 4 });
                }}
                icon={<ChevronDown size={16} aria-hidden="true" />}
              >
                {t('money.c360.more')}
              </Button>
            </div>
          </div>
          <div role="tablist" aria-label={t('money.c360.title')} className="flex gap-4 overflow-x-auto">
            {TABS.map((id) => (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={tab === id}
                onClick={() => setParams({ tab: id }, { replace: true })}
                className={`type-label h-10 shrink-0 border-b-2 ${
                  tab === id
                    ? 'border-brand-primary-600 text-brand-primary-700'
                    : 'border-transparent text-text-secondary'
                }`}
              >
                {t(`money.c360.tabs.${id}`)}
                {counts[id] != null ? ` (${counts[id]})` : ''}
              </button>
            ))}
          </div>
        </header>
        {menu ? (
          <Menu
            label={t('money.c360.more')}
            at={menu}
            width={260}
            onClose={() => setMenu(null)}
            entries={[
              {
                kind: 'item',
                id: 'statement',
                label: t('money.customer.statementLong'),
                icon: <ReceiptText size={16} />,
                disabled: readOnly,
                onSelect: () => {
                  setMenu(null);
                  navigate('/docs/reminders');
                },
              },
              {
                kind: 'item',
                id: 'offer',
                label: t('money.customer.offer'),
                icon: <FileText size={16} />,
                disabled: true,
                hint: t('documents.later', { phase: 6 }),
                onSelect: () => undefined,
              },
              {
                kind: 'item',
                id: 'order',
                label: t('money.c360.orderFromMail'),
                icon: <ShoppingCart size={16} />,
                disabled: true,
                hint: t('documents.later', { phase: 4 }),
                onSelect: () => undefined,
              },
            ]}
          />
        ) : null}
        <div className="flex max-w-[1120px] flex-col gap-4 p-4 md:p-6">
          {card.isError ? (
            <Banner
              kind="warning"
              message={t('money.c360.unavailable')}
              action={{ label: t('reminders.retry'), onClick: () => void card.refetch() }}
            />
          ) : null}
          {card.isPending && tab !== 'emails' ? (
            <div aria-busy="true" className="h-24 animate-pulse rounded-sm bg-bg-muted" />
          ) : null}
          {tab === 'emails' ? <Emails mail={mail.data} pending={mail.isPending} /> : null}
          {c && tab === 'overview' ? <Overview card={c} /> : null}
          {c && tab === 'documents' ? <Documents card={c} /> : null}
          {c && tab === 'contacts' ? <Contacts card={c} /> : null}
          {c && tab === 'activities' ? (
            <Panel title={t('money.customer.activities')} error={c.activities.error}>
              <Activities card={c} />
            </Panel>
          ) : null}
        </div>
      </main>
    </AppShell>
  );
}

function Chip({ children }: { children: ReactNode }) {
  return (
    <span className="type-small inline-flex h-6 items-center rounded-full border border-border-default bg-bg-subtle px-2 text-text-primary">
      {children}
    </span>
  );
}

function Kpi({ label, value, sub, edge }: { label: string; value: string; sub?: string | null; edge: string }) {
  return (
    <div className={`flex flex-col rounded-md border border-l-4 border-border-default p-3 ${edge}`}>
      <span className="type-small text-text-secondary">{label}</span>
      <span className="type-heading text-text-primary tabular-nums">{value}</span>
      {sub ? <span className="type-caption text-text-secondary">{sub}</span> : null}
    </div>
  );
}

function Panel({
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
    <section className="flex min-w-0 flex-col gap-2 rounded-lg border border-border-default p-3">
      <div className="flex items-center gap-2">
        <h2 className="type-micro min-w-0 flex-1 tracking-wide text-text-secondary uppercase">{title}</h2>
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

function Rows({ rows, empty }: { rows: { id: string; left: string; mid: string; right: string }[]; empty: string }) {
  if (rows.length === 0) return <p className="type-small text-text-secondary">{empty}</p>;
  return (
    <ul className="flex flex-col divide-y divide-border-default">
      {rows.map((row) => (
        <li key={row.id} className="type-small flex items-baseline gap-2 py-1.5 text-text-primary">
          <span className="shrink-0 font-medium">{row.left}</span>
          <span className="min-w-0 flex-1 truncate text-text-secondary">{row.mid}</span>
          {row.right ? <span className="shrink-0 tabular-nums">{row.right}</span> : null}
        </li>
      ))}
    </ul>
  );
}

function Overview({ card }: { card: CompanyCard }) {
  const { t } = useTranslation();
  const r = card.receivables;
  const last = card.orders.items[0];
  return (
    <>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3" data-testid="c360-kpis">
        <Kpi
          label={t('money.customer.openTitle')}
          value={r.error ? '–' : money(r.open_total)}
          sub={r.error ? null : t('money.customer.open', { count: r.open_count })}
          edge="border-l-brand-primary-600"
        />
        <Kpi
          label={t('money.customer.overdueTitle')}
          value={r.error ? '–' : money(r.overdue_total)}
          sub={r.oldest_overdue_days != null ? t('money.customer.days', { count: r.oldest_overdue_days }) : null}
          edge={r.overdue_count > 0 ? 'border-l-danger-600' : 'border-l-border-strong'}
        />
        <Kpi
          label={t('money.c360.lastOrder')}
          value={last ? day(last.issued_on) : '–'}
          sub={last ? `${last.number} · ${money(last.total)}` : t('money.customer.none')}
          edge="border-l-border-strong"
        />
      </div>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        <Panel
          title={t('money.customer.receivables')}
          error={r.error}
          action={
            <Link to="/docs/reminders" className="type-small text-brand-primary-700 hover:underline">
              {t('money.customer.statement')}
            </Link>
          }
        >
          <Invoices card={card} limit={5} />
        </Panel>
        <Panel
          title={t('money.customer.orders')}
          error={card.orders.error}
          action={
            <Link to="?tab=documents" replace className="type-small text-brand-primary-700 hover:underline">
              {t('money.c360.all')}
            </Link>
          }
        >
          <Orders card={card} limit={5} />
        </Panel>
        <Panel title={t('money.customer.activities')} error={card.activities.error}>
          <Activities card={card} limit={5} />
        </Panel>
      </div>
    </>
  );
}

function Invoices({ card, limit }: { card: CompanyCard; limit?: number }) {
  const { t } = useTranslation();
  return (
    <Rows
      rows={card.receivables.items.slice(0, limit).map((i) => ({
        id: i.id,
        left: i.number,
        mid: t('money.customer.dueOn', { date: day(i.due_on) }),
        right: money(i.remaining),
      }))}
      empty={t('money.customer.noOpen')}
    />
  );
}

function Orders({ card, limit }: { card: CompanyCard; limit?: number }) {
  const { t } = useTranslation();
  return (
    <Rows
      rows={card.orders.items.slice(0, limit).map((o) => ({
        id: o.id,
        left: o.number,
        mid: [day(o.issued_on), o.reference].filter(Boolean).join(' · '),
        right: money(o.total),
      }))}
      empty={t('money.customer.none')}
    />
  );
}

function Activities({ card, limit }: { card: CompanyCard; limit?: number }) {
  const { t } = useTranslation();
  return (
    <Rows
      rows={card.activities.items.slice(0, limit).map((a) => ({
        id: a.id,
        left: day(a.started_at),
        mid: a.description ?? '',
        right: '',
      }))}
      empty={t('money.customer.none')}
    />
  );
}

function Documents({ card }: { card: CompanyCard }) {
  const { t } = useTranslation();
  return (
    <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
      <Panel title={t('money.customer.receivables')} error={card.receivables.error}>
        <Invoices card={card} />
      </Panel>
      <Panel title={t('money.customer.orders')} error={card.orders.error}>
        <Orders card={card} />
      </Panel>
      <Panel title={t('money.customer.deliveries')} error={card.deliveries.error}>
        <Rows
          rows={card.deliveries.items.map((d) => ({
            id: d.id,
            left: d.number,
            mid: [day(d.issued_on), d.transport].filter(Boolean).join(' · '),
            right: money(d.total),
          }))}
          empty={t('money.customer.none')}
        />
      </Panel>
    </div>
  );
}

function Contacts({ card }: { card: CompanyCard }) {
  const { t } = useTranslation();
  if (card.persons.length === 0) return <p className="type-body text-text-secondary">{t('money.customer.none')}</p>;
  return (
    <ul className="flex flex-col divide-y divide-border-default rounded-md border border-border-default">
      {card.persons.map((p) => (
        <li key={p.money_id} className="flex items-center gap-3 px-3 py-2">
          <span
            aria-hidden="true"
            className="type-label flex size-9 shrink-0 items-center justify-center rounded-full bg-brand-primary-100 text-brand-primary-700"
          >
            {initials(p.name ?? '?')}
          </span>
          <span className="min-w-0 flex-1">
            <span className="type-label block truncate text-text-primary">{p.name ?? '–'}</span>
            <span className="type-small block truncate text-text-secondary">
              {[p.function, p.email, p.phone].filter(Boolean).join(' · ')}
            </span>
          </span>
        </li>
      ))}
    </ul>
  );
}

function Emails({
  mail,
  pending,
}: {
  mail: Awaited<ReturnType<typeof fetchCompanyMail>> | undefined;
  pending: boolean;
}) {
  const { t } = useTranslation();
  if (pending) return <div aria-busy="true" className="h-10 animate-pulse rounded-sm bg-bg-muted" />;
  if (!mail || mail.length === 0) return <p className="type-body text-text-secondary">{t('money.c360.noMail')}</p>;
  return (
    <ul
      className="flex flex-col divide-y divide-border-default rounded-md border border-border-default"
      data-testid="company-mail"
    >
      {mail.map((m) => (
        <li key={m.id}>
          <Link
            to={`/mail/${encodeURIComponent(m.mailbox_id)}/inbox/${encodeURIComponent(m.id)}`}
            className="flex items-center gap-3 px-3 py-2 hover:bg-bg-subtle"
          >
            {m.direction === 'in' ? (
              <ArrowDownLeft size={16} aria-label={t('money.c360.incoming')} className="shrink-0 text-text-secondary" />
            ) : (
              <ArrowUpRight size={16} aria-label={t('money.c360.outgoing')} className="shrink-0 text-text-secondary" />
            )}
            <span className="min-w-0 flex-1">
              <span className="type-label block truncate text-text-primary">{m.subject || t('search.noSubject')}</span>
              <span className="type-small block truncate text-text-secondary">{m.from_name || m.from_email}</span>
            </span>
            <span className="type-small shrink-0 text-text-secondary">
              {m.received_at ? new Date(m.received_at).toLocaleDateString('sk-SK') : ''}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
