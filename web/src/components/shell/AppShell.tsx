import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2, RefreshCw, TriangleAlert } from 'lucide-react';
import { useCallback, useEffect, useState, useSyncExternalStore, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { fetchMe, logout } from '../../features/auth/authApi';
import { ScreenM18 } from '../../features/more/ScreenM18';
import { fetchPicker, PICKER_KEY } from '../../features/persons/personsApi';
import { useIdleAsk } from '../../features/persons/useIdleAsk';
import { CommandPaletteHost } from '../../features/search/CommandPalette';
import { SystemHost } from '../../features/system/SystemHost';
import { useGlobalShortcuts } from '../../features/system/useGlobalShortcuts';
import { ApiError } from '../../lib/api';
import { MOBILE_QUERY, useMediaQuery } from '../../lib/useMediaQuery';
import { Banner } from '../Banner';
import { Button } from '../Button';
import { StatusPage } from '../StatusPage';
import { BottomNav, type BottomSection } from './BottomNav';
import { DropZone } from './DropZone';
import { Rail, type RailSection } from './Rail';

/** How long a hung `/api/auth/me` may leave only a loading shell (pilot #18 B2). */
export const ME_LOAD_TIMEOUT_MS = 10_000;

function useOnline(): boolean {
  return useSyncExternalStore(
    (onChange) => {
      window.addEventListener('online', onChange);
      window.addEventListener('offline', onChange);
      return () => {
        window.removeEventListener('online', onChange);
        window.removeEventListener('offline', onChange);
      };
    },
    () => navigator.onLine,
    () => true,
  );
}

function bottomOf(section: RailSection, moreOpen: boolean): BottomSection {
  if (moreOpen) return 'more';
  if (section === 'contacts') return 'contacts';
  if (section === 'settings') return 'more';
  return 'mail';
}

type Props = {
  section: RailSection;
  mailbox?: string;
  unread?: number;
  children: ReactNode;
  /** Hide bottom nav (e.g. M3 thread detail, M4 compose). */
  hideBottomNav?: boolean;
};

/** Signed-in shell: desktop G1 rail; mobile bottom nav + M18 Viac overlay. */
export function AppShell({ section, mailbox = 'default', unread = 0, children, hideBottomNav = false }: Props) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const online = useOnline();
  const mobile = useMediaQuery(MOBILE_QUERY);
  const [moreOpen, setMoreOpen] = useState(false);
  const me = useQuery({ queryKey: ['me'], queryFn: fetchMe, retry: false });
  const picker = useQuery({ queryKey: PICKER_KEY, queryFn: fetchPicker, enabled: me.data?.kind === 'branch' });
  useIdleAsk(picker.data?.idle_ask_minutes, (picker.data?.persons.length ?? 0) > 1);
  useGlobalShortcuts();

  const signOut = useCallback(async () => {
    try {
      await logout();
    } finally {
      queryClient.clear();
      navigate('/login', { replace: true });
    }
  }, [navigate, queryClient]);

  const [waitGen, setWaitGen] = useState(0);
  const [timedOut, setTimedOut] = useState(false);
  useEffect(() => {
    if (me.data || me.isError) return;
    const id = window.setTimeout(() => setTimedOut(true), ME_LOAD_TIMEOUT_MS);
    return () => window.clearTimeout(id);
  }, [me.data, me.isError, me.isFetching, waitGen]);

  const showError = me.isError || (timedOut && !me.data);
  const retryMe = () => {
    setTimedOut(false);
    setWaitGen((g) => g + 1);
    void me.refetch();
  };

  if (showError) {
    const ref =
      me.error instanceof ApiError && typeof me.error.detail.ref === 'string' ? String(me.error.detail.ref) : '';
    return (
      <StatusPage
        tone="danger"
        data-testid="shell-load-error"
        icon={<TriangleAlert size={44} strokeWidth={1.5} />}
        code={ref ? t('system.error.code', { ref }) : t('system.error.codeNoRef')}
        title={t('system.loadFailed.title')}
        text={t('system.loadFailed.text')}
        actions={
          <Button icon={<RefreshCw size={16} />} onClick={retryMe}>
            {t('system.retry')}
          </Button>
        }
      />
    );
  }

  if (!me.data) {
    return (
      <main
        className="flex h-full flex-col items-center justify-center gap-3 bg-bg-subtle text-text-secondary"
        aria-busy="true"
        data-testid="shell-loading"
      >
        <Loader2 size={28} className="animate-spin text-brand-primary-600" aria-hidden="true" />
        <p className="type-body">{t('system.loading.title')}</p>
        <p className="type-small text-text-tertiary">{t('system.loading.text')}</p>
      </main>
    );
  }

  if (mobile) {
    return (
      <div className="flex h-full min-h-0 flex-col bg-bg-canvas" data-testid="mobile-shell">
        {online ? null : <Banner kind="offline" message={t('shell.offline')} />}
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          {moreOpen ? <ScreenM18 onClose={() => setMoreOpen(false)} onLogout={() => void signOut()} /> : children}
        </div>
        {hideBottomNav ? null : (
          <BottomNav
            section={bottomOf(section, moreOpen)}
            mailbox={mailbox}
            unread={unread}
            onMore={() => setMoreOpen(true)}
            onLeaveMore={() => setMoreOpen(false)}
          />
        )}
        <DropZone />
        <SystemHost />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0">
      <Rail section={section} mailbox={mailbox} unread={unread} onLogout={() => void signOut()} />
      <div className="flex min-w-0 flex-1 flex-col">
        {online ? null : <Banner kind="offline" message={t('shell.offline')} />}
        <div className="flex min-h-0 flex-1">{children}</div>
      </div>
      <DropZone />
      <CommandPaletteHost />
      <SystemHost />
    </div>
  );
}
