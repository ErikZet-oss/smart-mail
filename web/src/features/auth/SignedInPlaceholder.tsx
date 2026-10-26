import { useQuery } from '@tanstack/react-query';
import { LogOut } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { Button } from '../../components/Button';
import { Logo } from '../../components/Logo';
import { fetchMe, logout } from './authApi';

/**
 * Temporary landing page of Phase 1a for `/who` (W1b, built in 1b) and the mail routes (W2, built in 1c): proves the
 * session works end-to-end and offers Odhlásiť. Replaced screen by screen in the next parts of Phase 1.
 */
export function SignedInPlaceholder() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const me = useQuery({ queryKey: ['me'], queryFn: fetchMe, retry: false });
  const [leaving, setLeaving] = useState(false);

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
    <main className="flex min-h-full flex-col items-center justify-center gap-3 bg-bg-subtle p-6 text-center">
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
  );
}
