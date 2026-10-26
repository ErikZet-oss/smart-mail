import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';

import { AppShell } from '../../components/shell/AppShell';
import { fetchMe } from '../auth/authApi';

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="type-label text-text-secondary">{label}</span>
      <span className="type-body text-text-primary">{value || '—'}</span>
    </div>
  );
}

/** W12 Nastavenia — `/settings/:section/:sub?`. The settings sections are built in 1f; until then only Môj profil
 * (03b, the target of the PersonChip menu) shows the active person read-only. */
export function ScreenW12() {
  const { t } = useTranslation();
  const { section, sub } = useParams();
  const me = useQuery({ queryKey: ['me'], queryFn: fetchMe, retry: false });
  const person = me.data?.person ?? null;
  const isProfile = section === 'identity' && sub === 'profile';
  const title = isProfile ? t('settings.profile.title') : t('settings.title');

  return (
    <AppShell section="settings">
      <main className="flex min-w-0 flex-1 flex-col bg-bg-canvas">
        <header className="flex h-14 shrink-0 items-center border-b border-border-default px-6">
          <h1 className="type-heading text-text-primary">{isProfile ? `${t('settings.title')} › ${title}` : title}</h1>
        </header>
        <div className="flex max-w-[640px] flex-col gap-5 p-6">
          {isProfile && person ? (
            <>
              <Field label={t('settings.profile.firstName')} value={person.first_name} />
              <Field label={t('settings.profile.lastName')} value={person.last_name} />
              <Field label={t('settings.profile.function')} value={person.function ?? ''} />
              <Field label={t('settings.profile.login')} value={me.data?.email ?? ''} />
              <p className="type-small text-text-secondary">{t('settings.later')}</p>
            </>
          ) : (
            <p className="type-body text-text-secondary">
              {isProfile ? t('settings.profile.noPerson') : t('settings.later')}
            </p>
          )}
        </div>
      </main>
    </AppShell>
  );
}
