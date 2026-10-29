import { useQueryClient } from '@tanstack/react-query';
import { ShieldCheck } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { Button } from '../../components/Button';
import { Logo } from '../../components/Logo';
import { EnableTwoFactorDialog } from '../settings/TwoFactor';
import { fetchMe, logout } from './authApi';

/** W1a in setup mode (#77 „Vyžadovať 2FA“): the login is limited to setting up two-factor authentication. The same
 * dialog as Settings 09; afterwards the session is a normal one. */
export function MfaSetup() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);

  async function done() {
    setOpen(false);
    queryClient.clear();
    const me = await fetchMe();
    navigate(me.needs_person ? '/who' : '/', { replace: true });
  }

  return (
    <main className="flex min-h-full flex-col items-center justify-center bg-bg-canvas px-4 py-10">
      <div className="flex w-full max-w-[380px] flex-col items-center gap-3.5 text-center" data-testid="mfa-setup">
        <Logo width={120} />
        <div aria-hidden="true" className="h-2" />
        <h1 className="type-title text-text-primary">{t('mfa.setup.title')}</h1>
        <p className="type-small text-text-secondary">{t('mfa.setup.body')}</p>
        <Button type="button" size="lg" className="w-full" onClick={() => setOpen(true)}>
          <ShieldCheck size={18} aria-hidden="true" />
          {t('mfa.setup.start')}
        </Button>
        <button
          type="button"
          className="type-label rounded-xs text-brand-primary-600 hover:underline"
          onClick={() =>
            void logout()
              .catch(() => undefined)
              .then(() => {
                queryClient.clear();
                navigate('/login', { replace: true });
              })
          }
        >
          {t('mfa.setup.logout')}
        </button>
      </div>
      {open ? <EnableTwoFactorDialog onClose={() => setOpen(false)} onEnabled={() => void done()} /> : null}
    </main>
  );
}
