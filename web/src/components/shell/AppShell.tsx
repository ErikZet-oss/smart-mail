import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useState, useSyncExternalStore, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { fetchMe, logout } from '../../features/auth/authApi';
import { fetchPicker, PICKER_KEY } from '../../features/persons/personsApi';
import { useIdleAsk } from '../../features/persons/useIdleAsk';
import { CommandPaletteHost } from '../../features/search/CommandPalette';
import { MOBILE_QUERY, useMediaQuery } from '../../lib/useMediaQuery';
import { Banner } from '../Banner';
import { BottomNav, type BottomSection } from './BottomNav';
import { DropZone } from './DropZone';
import { MobileMoreSheet } from './MobileMoreSheet';
import { Rail, type RailSection } from './Rail';

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

function bottomOf(section: RailSection): BottomSection {
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

/** Signed-in shell: desktop G1 rail; mobile bottom nav (M1) + Viac sheet. */
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

  const signOut = useCallback(async () => {
    try {
      await logout();
    } finally {
      queryClient.clear();
      navigate('/login', { replace: true });
    }
  }, [navigate, queryClient]);

  if (!me.data) return <main className="h-full bg-bg-subtle" aria-busy="true" />;

  if (mobile) {
    return (
      <div className="flex h-full min-h-0 flex-col bg-bg-canvas" data-testid="mobile-shell">
        {online ? null : <Banner kind="offline" message={t('shell.offline')} />}
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">{children}</div>
        {hideBottomNav ? null : (
          <BottomNav section={bottomOf(section)} mailbox={mailbox} unread={unread} onMore={() => setMoreOpen(true)} />
        )}
        <MobileMoreSheet open={moreOpen} onClose={() => setMoreOpen(false)} onLogout={() => void signOut()} />
        <DropZone />
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
    </div>
  );
}
