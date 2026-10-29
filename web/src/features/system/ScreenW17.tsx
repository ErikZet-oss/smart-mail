import { useQuery } from '@tanstack/react-query';
import { LoaderCircle, RefreshCw, WandSparkles } from 'lucide-react';
import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useLocation, useNavigate } from 'react-router-dom';

import { Button } from '../../components/Button';
import { Logo } from '../../components/Logo';
import { StatusPage } from '../../components/StatusPage';
import { safeInternalPath } from '../../lib/safePath';
import { api } from '../../lib/api';

type Maintenance = { active: boolean; until: string | null };

const POLL_MS = 60_000;

function untilText(until: string | null | undefined, t: (key: string, options?: Record<string, string>) => string) {
  const date = until ? new Date(until) : null;
  if (!date || Number.isNaN(date.getTime())) return t('system.maintenance.untilUnknown');
  const time = date.toLocaleTimeString('sk-SK', { hour: 'numeric', minute: '2-digit' });
  if (date.toDateString() === new Date().toDateString()) return t('system.maintenance.untilToday', { time });
  const day = date.toLocaleDateString('sk-SK', { day: 'numeric', month: 'numeric', year: 'numeric' });
  return t('system.maintenance.untilDate', { date: day, time });
}

/** W17 Údržba – shown while the API answers 503 `maintenance`; goes back as soon as it is over. */
export function ScreenW17() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const from = safeInternalPath((location.state as { from?: unknown } | null)?.from);
  const status = useQuery({
    queryKey: ['maintenance'],
    queryFn: () => api<Maintenance>('GET', '/api/system/maintenance', undefined, { global: false }),
    refetchInterval: POLL_MS,
  });

  const over = status.data?.active === false;
  useEffect(() => {
    if (over) navigate(from, { replace: true });
  }, [over, from, navigate]);

  return (
    <StatusPage
      tone="brand"
      top={<Logo width={160} />}
      icon={<WandSparkles size={44} strokeWidth={1.5} />}
      title={t('system.maintenance.title')}
      textWidth={560}
      text={`${untilText(status.data?.until, t)} ${t('system.maintenance.mailWorks')}`}
      actions={
        // "Čítať uložené správy" needs the offline message cache (PWA, later in Phase 1) – not offered yet
        <Button
          icon={
            status.isFetching ? (
              <LoaderCircle size={16} className="animate-spin" aria-hidden="true" />
            ) : (
              <RefreshCw size={16} aria-hidden="true" />
            )
          }
          onClick={() => void status.refetch()}
        >
          {t('system.retry')}
        </Button>
      }
    />
  );
}
