import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useSyncExternalStore, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { fetchMe, logout } from '../../features/auth/authApi';
import { fetchPicker, PICKER_KEY } from '../../features/persons/personsApi';
import { useIdleAsk } from '../../features/persons/useIdleAsk';
import { Banner } from '../Banner';
import { DropZone } from './DropZone';
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

type Props = { section: RailSection; mailbox?: string; unread?: number; children: ReactNode };

/** Signed-in shell (SCREENS_SPEC §2): G1 rail, G6 offline banner on top of the content, G7 drop zone. */
export function AppShell({ section, mailbox = 'default', unread = 0, children }: Props) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const online = useOnline();
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
  return (
    <div className="flex h-full min-h-0">
      <Rail section={section} mailbox={mailbox} unread={unread} onLogout={() => void signOut()} />
      <div className="flex min-w-0 flex-1 flex-col">
        {online ? null : <Banner kind="offline" message={t('shell.offline')} />}
        <div className="flex min-h-0 flex-1">{children}</div>
      </div>
      <DropZone />
    </div>
  );
}
