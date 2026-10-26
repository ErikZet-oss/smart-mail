import { ArrowLeft, Copy, Inbox, Lock, Mail, RefreshCw, Search, TriangleAlert } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';

import { Button } from '../../components/Button';
import { StatusPage } from '../../components/StatusPage';
import { api, formatRef } from '../../lib/api';

const ICON = 44;
const BUTTON_ICON = 16;

type SystemInfo = { admin_contact_email: string | null };

/** W16a 403 – the person's role does not allow this page. */
export function ScreenW16a() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? location.pathname;
  const subject = encodeURIComponent(t('system.forbidden.mailSubject', { path: from }));
  const info = useQuery({
    queryKey: ['system', 'info'],
    queryFn: () => api<SystemInfo>('GET', '/api/system/info', undefined, { global: false }),
    staleTime: Infinity,
  });
  const to = encodeURIComponent(info.data?.admin_contact_email ?? '');
  return (
    <StatusPage
      icon={<Lock size={ICON} strokeWidth={1.5} />}
      code={t('system.forbidden.code')}
      title={t('system.forbidden.title')}
      text={t('system.forbidden.text')}
      actions={
        <>
          <Button variant="secondary" icon={<ArrowLeft size={BUTTON_ICON} />} onClick={() => navigate(-1)}>
            {t('system.back')}
          </Button>
          <a
            href={`mailto:${to}?subject=${subject}`}
            className="type-label inline-flex h-8 items-center gap-2 rounded-sm bg-brand-primary-600 px-3 text-text-on-primary hover:bg-brand-primary-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-primary-500"
          >
            <Mail size={BUTTON_ICON} aria-hidden="true" />
            {t('system.forbidden.askAdmin')}
          </a>
        </>
      }
    />
  );
}

/** W16b 404 – also the catch-all route. */
export function ScreenW16b() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  return (
    <StatusPage
      icon={<Search size={ICON} strokeWidth={1.5} />}
      code={t('system.notFound.code')}
      title={t('system.notFound.title')}
      text={t('system.notFound.text')}
      actions={
        <>
          <Button variant="secondary" icon={<Inbox size={BUTTON_ICON} />} onClick={() => navigate('/')}>
            {t('system.inbox')}
          </Button>
          <Button icon={<Search size={BUTTON_ICON} />} onClick={() => navigate('/search')}>
            {t('system.search')}
          </Button>
        </>
      }
    />
  );
}

/** W16c 500 – unexpected server error with the reference code from the API (`ref`). */
export function ScreenW16c() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const ref = formatRef(params.get('ref') ?? '');
  const from = (location.state as { from?: string } | null)?.from ?? '/';
  const [copied, setCopied] = useState(false);

  async function copy() {
    await navigator.clipboard.writeText(ref);
    setCopied(true);
  }

  return (
    <StatusPage
      tone="danger"
      icon={<TriangleAlert size={ICON} strokeWidth={1.5} />}
      code={ref ? t('system.error.code', { ref }) : t('system.error.codeNoRef')}
      title={t('system.error.title')}
      text={t('system.error.text')}
      actions={
        <>
          <Button icon={<RefreshCw size={BUTTON_ICON} />} onClick={() => navigate(from, { replace: true })}>
            {t('system.retry')}
          </Button>
          {ref ? (
            <Button variant="secondary" icon={<Copy size={BUTTON_ICON} />} onClick={() => void copy()}>
              <span aria-live="polite">{copied ? t('system.error.copied') : t('system.error.copy')}</span>
            </Button>
          ) : null}
        </>
      }
    />
  );
}
