import { useQuery } from '@tanstack/react-query';
import { LogOut } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { Button } from '../../components/Button';
import { Logo } from '../../components/Logo';
import { PersonChip } from '../persons/PersonChip';
import { fetchPicker, PICKER_KEY } from '../persons/personsApi';
import { useIdleAsk } from '../persons/useIdleAsk';
import { fetchMe, logout } from './authApi';

/**
 * Temporary landing page for the mail routes (W2, built in 1c): proves the session works end-to-end and offers
 * Odhlásiť. The 72 px strip on the left holds only the W2b PersonChip until the G1 rail of 1c replaces it.
 */
export function SignedInPlaceholder() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const me = useQuery({ queryKey: ['me'], queryFn: fetchMe, retry: false });
  const picker = useQuery({ queryKey: PICKER_KEY, queryFn: fetchPicker, enabled: me.data?.kind === 'branch' });
  const [leaving, setLeaving] = useState(false);
  useIdleAsk(picker.data?.idle_ask_minutes, (picker.data?.persons.length ?? 0) > 1);

  async function signOut() {
    setLeaving(true);
    try {
      await logout();
    } finally {
      navigate('/login', { replace: true });
    }
  }

  if (!me.data) return <main className="min-h-full bg-bg-subtle" aria-busy="true" />;
  const person = me.data.person;
  return (
    <div className="flex min-h-full">
      <nav className="flex w-[72px] shrink-0 flex-col justify-end bg-bg-rail pb-2" aria-label={t('person.switch')}>
        <PersonChip />
      </nav>
      <main className="flex flex-1 flex-col items-center justify-center gap-3 bg-bg-subtle p-6 text-center">
        <Logo width={120} />
        <h1 className="type-title text-text-primary">{t('signedIn.title')}</h1>
        <p className="type-body text-text-secondary">{t('signedIn.as', { email: me.data.email })}</p>
        <p className="type-small text-text-secondary">
          {person ? t('signedIn.person', { name: person.full_name }) : t('signedIn.noPerson')}
        </p>
        <Button variant="secondary" icon={<LogOut size={16} />} onClick={() => void signOut()} disabled={leaving}>
          {t('signedIn.logout')}
        </Button>
      </main>
    </div>
  );
}
