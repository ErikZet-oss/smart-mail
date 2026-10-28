import { useQuery, useQueryClient } from '@tanstack/react-query';
import { CornerDownLeft, Flag } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useLocation, useNavigate } from 'react-router-dom';

import { Avatar } from '../../components/Avatar';
import { Button } from '../../components/Button';
import { Logo } from '../../components/Logo';
import { Switch } from '../../components/Switch';
import { MOBILE_QUERY, useMediaQuery } from '../../lib/useMediaQuery';
import { refreshAfterPersonChange } from '../../lib/sessionCache';
import { logout, returnTo, type Person } from '../auth/authApi';
import { choosePerson, fetchPicker, initials, PICKER_KEY } from './personsApi';

type TileProps = {
  person: Person;
  selected: boolean;
  mobile: boolean;
  disabled: boolean;
  onChoose: () => void;
};

/** Figma `PersonTile` (W1b 132 × 140; M0 half width, two initials, no flag). */
function PersonTile({ person, selected, mobile, disabled, onChoose }: TileProps) {
  const { t } = useTranslation();
  return (
    <li className={mobile ? 'min-w-0' : undefined}>
      <button
        type="button"
        onClick={onChoose}
        disabled={disabled}
        aria-current={selected ? 'true' : undefined}
        className={`relative flex flex-col items-center justify-center gap-2 rounded-lg text-center transition-colors duration-[var(--motion-hover)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-primary-500 disabled:cursor-wait ${
          mobile ? 'w-full p-4' : 'h-[140px] w-[132px] px-2 py-3'
        } ${
          selected
            ? `border-2 bg-brand-primary-50 ${mobile ? 'border-brand-primary-500' : 'border-brand-primary-600'}`
            : 'border border-border-default bg-bg-canvas hover:bg-bg-subtle'
        }`}
      >
        <Avatar initials={initials(person, mobile ? 2 : 1)} seed={person.id} size={56} />
        <span className="flex w-full flex-col items-center gap-0.5">
          <span className={`text-text-primary ${mobile ? 'type-body-strong' : 'type-heading w-[116px]'}`}>
            {person.full_name}
          </span>
          {person.function ? <span className="type-caption text-text-secondary">{person.function}</span> : null}
        </span>
        {person.is_manager && !mobile ? (
          <span
            title={t('person.manager')}
            className={`absolute flex h-[18px] items-center rounded-full bg-success-50 px-[5px] text-success-600 ${
              selected ? 'right-[6px] top-[6px]' : 'right-[7px] top-[7px]'
            }`}
          >
            <Flag size={12} aria-hidden="true" />
            <span className="sr-only">{t('person.manager')}</span>
          </span>
        ) : null}
      </button>
    </li>
  );
}

/**
 * W1b / M0 Kto ste? (`/who`, UX_SPEC W1b, PRODUCT_SPEC §2.0): one click on a person = done, no PIN (D9). The person
 * remembered on this device (or the current one when the idle re-ask brings the picker back) is preselected and
 * "Pokračovať ako …" continues with Enter.
 */
export function ScreenW1b() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const mobile = useMediaQuery(MOBILE_QUERY);
  const picker = useQuery({ queryKey: PICKER_KEY, queryFn: fetchPicker, staleTime: 0 });
  const [rememberPhone, setRememberPhone] = useState(true);
  const [busy, setBusy] = useState(false);
  const continueRef = useRef<HTMLButtonElement>(null);

  const data = picker.data;
  const preselectedId = data?.last_person_id ?? data?.current_person_id ?? null;
  const preselected = data?.persons.find((p) => p.id === preselectedId) ?? null;

  useEffect(() => {
    if (preselected && !mobile) continueRef.current?.focus();
  }, [preselected, mobile]);

  useEffect(() => {
    if (!preselected) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Enter' && (document.activeElement === document.body || !document.activeElement)) {
        event.preventDefault();
        continueRef.current?.click();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [preselected]);

  async function choose(person: Person) {
    if (busy) return;
    setBusy(true);
    try {
      const me = await choosePerson(person.id, mobile ? rememberPhone : true);
      queryClient.setQueryData(['me'], me);
      await refreshAfterPersonChange(queryClient);
      navigate(returnTo(location.state), { replace: true });
    } catch {
      // person deactivated or moved meanwhile: show the current list again
      setBusy(false);
      await picker.refetch();
    }
  }

  async function otherEmail() {
    try {
      await logout();
    } finally {
      navigate('/login', { replace: true });
    }
  }

  if (!data) return <main className="min-h-full bg-bg-subtle" aria-busy="true" />;

  const subtitle = data.branch ? t('person.subtitle', { branch: data.branch, email: data.email }) : data.email;
  const tiles = (
    <ul
      className={mobile ? 'grid w-full grid-cols-2 gap-3' : 'flex flex-wrap justify-center gap-4'}
      aria-label={t('person.title')}
    >
      {data.persons.map((person) => (
        <PersonTile
          key={person.id}
          person={person}
          selected={person.id === preselectedId}
          mobile={mobile}
          disabled={busy}
          onChoose={() => void choose(person)}
        />
      ))}
    </ul>
  );

  if (mobile) {
    return (
      <main className="flex min-h-full flex-col gap-4 bg-bg-canvas px-4 py-6" aria-busy={busy || undefined}>
        <h1 className="type-title text-text-primary">{t('person.title')}</h1>
        <p className="type-small text-text-secondary">{subtitle}</p>
        {tiles}
        <Switch checked={rememberPhone} onChange={setRememberPhone} label={t('person.rememberPhone')} />
        <p className="type-caption text-text-tertiary">{t('person.mobileHint')}</p>
      </main>
    );
  }

  return (
    <main className="flex min-h-full items-center justify-center bg-bg-subtle p-6" aria-busy={busy || undefined}>
      <section className="flex w-[640px] max-w-full flex-col items-center gap-5 rounded-[16px] border border-border-default bg-bg-canvas px-12 py-10 shadow-e2">
        <Logo width={120} />
        <div className="flex flex-col items-center gap-1 text-center">
          <h1 className="type-display text-text-primary">{t('person.title')}</h1>
          <p className="type-small text-text-secondary">{subtitle}</p>
        </div>
        {tiles}
        {preselected ? (
          <Button
            ref={continueRef}
            size="lg"
            className="w-[300px] max-w-full"
            disabled={busy}
            onClick={() => void choose(preselected)}
          >
            {t('person.continue', { name: preselected.first_name })}
            <CornerDownLeft size={14} aria-hidden="true" />
          </Button>
        ) : null}
        <div className="flex flex-col items-center gap-0.5 text-center">
          <p className="type-small text-text-primary">{t('person.oneClick')}</p>
          <p className="type-caption text-text-secondary">{t('person.deviceRemembers')}</p>
        </div>
        <button
          type="button"
          onClick={() => void otherEmail()}
          className="type-label text-brand-primary-600 underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-primary-500"
        >
          {t('person.otherEmail')}
        </button>
      </section>
    </main>
  );
}
