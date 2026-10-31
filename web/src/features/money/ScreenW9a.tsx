import { useQuery } from '@tanstack/react-query';
import { ArrowDownLeft, ArrowLeft, ArrowUpRight, Mail } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link, Navigate, useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { Banner } from '../../components/Banner';
import { Button } from '../../components/Button';
import { AppShell } from '../../components/shell/AppShell';
import { fetchMe } from '../auth/authApi';
import { useFeaturesState } from '../system/features';
import { CustomerCard, type MobileTab } from './CustomerPanel';
import { cardKey, fetchCard, fetchCompanyMail } from './moneyApi';

type Tab = MobileTab | 'emails';
const TABS: Tab[] = ['overview', 'emails', 'documents', 'contacts'];

/**
 * W9a Zákazník 360 — `/contacts/company/:moneyId` (Phase 3g, SCREENS_SPEC): header and tabs Prehľad · E-maily ·
 * Doklady · Kontakty a aktivity. Read-only towards Money; Objednávky (W9b) and ponuky come in later phases.
 */
export function ScreenW9a() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { moneyId = '' } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = (TABS.includes(params.get('tab') as Tab) ? params.get('tab') : 'overview') as Tab;
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
    enabled: features.money && tab === 'emails',
  });
  if (features.loaded && !features.money) return <Navigate to="/404" replace />;
  const company = card.data?.company;
  const readOnly = !me.data?.person || Boolean(me.data.read_only);
  const contact = company?.email ?? card.data?.persons.find((p) => p.email)?.email ?? null;

  return (
    <AppShell section="contacts">
      <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto bg-bg-canvas" data-testid="screen-w9a">
        <header className="flex flex-col gap-3 border-b border-border-default px-4 pt-4 md:px-6">
          <div className="flex items-start gap-2">
            <button
              type="button"
              onClick={() => navigate(-1)}
              aria-label={t('system.back')}
              className="flex size-9 shrink-0 items-center justify-center rounded-sm text-text-secondary hover:bg-bg-subtle"
            >
              <ArrowLeft size={18} aria-hidden="true" />
            </button>
            <div className="min-w-0 flex-1">
              <h1 className="type-title truncate text-text-primary">{company?.name ?? t('money.c360.title')}</h1>
              {company ? (
                <p className="type-small text-text-secondary">
                  {[
                    company.ico ? t('money.customer.ico', { ico: company.ico }) : null,
                    company.dic ? t('money.c360.dic', { dic: company.dic }) : null,
                    company.icdph ? t('money.customer.icdph', { icdph: company.icdph }) : null,
                    company.code,
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                </p>
              ) : null}
            </div>
            <Button
              type="button"
              disabled={!contact || readOnly}
              onClick={() => navigate(`/compose?to=${encodeURIComponent(contact ?? '')}`)}
              icon={<Mail size={16} aria-hidden="true" />}
            >
              {t('money.customer.write')}
            </Button>
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
              </button>
            ))}
          </div>
        </header>
        <div className="flex max-w-[960px] flex-col gap-4 p-4 md:p-6">
          {card.isError ? (
            <Banner
              kind="warning"
              message={t('money.c360.unavailable')}
              action={{ label: t('reminders.retry'), onClick: () => void card.refetch() }}
            />
          ) : null}
          {tab === 'emails' ? (
            mail.isPending ? (
              <div aria-busy="true" className="h-10 animate-pulse rounded-sm bg-bg-muted" />
            ) : (mail.data ?? []).length === 0 ? (
              <p className="type-body text-text-secondary">{t('money.c360.noMail')}</p>
            ) : (
              <ul
                className="flex flex-col divide-y divide-border-default rounded-md border border-border-default"
                data-testid="company-mail"
              >
                {(mail.data ?? []).map((m) => (
                  <li key={m.id}>
                    <Link
                      to={`/mail/${encodeURIComponent(m.mailbox_id)}/inbox/${encodeURIComponent(m.id)}`}
                      className="flex items-center gap-3 px-3 py-2 hover:bg-bg-subtle"
                    >
                      {m.direction === 'in' ? (
                        <ArrowDownLeft
                          size={16}
                          aria-label={t('money.c360.incoming')}
                          className="shrink-0 text-text-secondary"
                        />
                      ) : (
                        <ArrowUpRight
                          size={16}
                          aria-label={t('money.c360.outgoing')}
                          className="shrink-0 text-text-secondary"
                        />
                      )}
                      <span className="min-w-0 flex-1">
                        <span className="type-label block truncate text-text-primary">
                          {m.subject || t('search.noSubject')}
                        </span>
                        <span className="type-small block truncate text-text-secondary">
                          {m.from_name || m.from_email}
                        </span>
                      </span>
                      <span className="type-small shrink-0 text-text-secondary">
                        {m.received_at ? new Date(m.received_at).toLocaleDateString('sk-SK') : ''}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )
          ) : company ? (
            <CustomerCard
              company={company}
              method=""
              email={contact ?? ''}
              card={card.data}
              pending={card.isPending}
              error={card.isError}
              only={tab}
              messageId=""
              mailbox="default"
              readOnly={readOnly}
            />
          ) : card.isPending ? (
            <div aria-busy="true" className="h-24 animate-pulse rounded-sm bg-bg-muted" />
          ) : null}
        </div>
      </main>
    </AppShell>
  );
}
