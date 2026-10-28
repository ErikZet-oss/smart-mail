import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Bell, ChevronRight, CircleHelp, LogOut, Moon, Settings, UserCheck, Users } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import { Avatar } from '../../components/Avatar';
import { fetchMe } from '../auth/authApi';
import { choosePerson, fetchPicker, initials, PICKER_KEY } from '../persons/personsApi';
import { useTheme } from '../prefs/ThemeProvider';
import type { UiPrefs } from '../prefs/prefsApi';
import { useSystemUi } from '../system/systemUi';

type Props = {
  onClose: () => void;
  onLogout: () => void;
};

const THEME_OPTS: { value: UiPrefs['theme']; labelKey: string }[] = [
  { value: 'light', labelKey: 'prefs.themeLight' },
  { value: 'dark', labelKey: 'prefs.themeDark' },
  { value: 'system', labelKey: 'prefs.themeSystem' },
];

/**
 * M18 Viac — Phase 1 items (SCREENS_SPEC §13): Kontakty, Nastavenia, Notifikácie, Prepnúť osobu,
 * Vzhľad, O systéme (W15b), Odhlásiť.
 */
export function ScreenM18({ onClose, onLogout }: Props) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { theme, setTheme } = useTheme();
  const { open } = useSystemUi();
  const me = useQuery({ queryKey: ['me'], queryFn: fetchMe, retry: false });
  const picker = useQuery({ queryKey: PICKER_KEY, queryFn: fetchPicker });
  const [switchOpen, setSwitchOpen] = useState(false);

  const person = me.data?.person;
  const persons = picker.data?.persons ?? [];
  const canSwitch = persons.length > 1;
  const others = persons.filter((p) => p.id !== picker.data?.current_person_id);

  const switchPerson = useMutation({
    mutationFn: (personId: string) => choosePerson(personId, true),
    onSuccess: (next) => {
      queryClient.setQueryData(['me'], next);
      void queryClient.invalidateQueries({ queryKey: PICKER_KEY });
      setSwitchOpen(false);
    },
  });

  const branchLabel = me.data?.branch
    ? [me.data.branch, person?.function || person?.role].filter(Boolean).join(' · ')
    : (person?.function ?? person?.role ?? '');

  return (
    <div className="flex h-full min-h-0 flex-col bg-bg-canvas" data-testid="screen-m18">
      <header className="flex h-12 shrink-0 items-center gap-1 border-b border-border-default px-1">
        <button
          type="button"
          onClick={onClose}
          aria-label={t('system.back')}
          className="flex size-11 items-center justify-center rounded-sm text-text-primary hover:bg-bg-subtle"
        >
          <ArrowLeft size={22} />
        </button>
        <h1 className="type-heading min-w-0 flex-1 truncate text-text-primary">{t('mobile.more')}</h1>
        {person ? (
          <span className="mr-2" aria-hidden="true">
            <Avatar initials={initials(person, 1)} seed={person.id} size={32} />
          </span>
        ) : null}
      </header>

      {person ? (
        <div className="flex items-center gap-3 border-b border-border-default px-4 py-4">
          <Avatar initials={initials(person, 2)} seed={person.id} size={56} />
          <div className="min-w-0 flex-1">
            <p className="type-heading truncate text-text-primary">{person.full_name}</p>
            {branchLabel ? <p className="type-caption truncate text-text-secondary">{branchLabel}</p> : null}
          </div>
          {canSwitch ? (
            <button
              type="button"
              onClick={() => setSwitchOpen((v) => !v)}
              className="type-caption shrink-0 rounded-sm border border-border-default px-2.5 py-2 text-text-primary hover:bg-bg-subtle"
            >
              {t('person.switchAction')}
            </button>
          ) : null}
        </div>
      ) : null}

      {switchOpen && canSwitch ? (
        <ul
          className="border-b border-border-default bg-bg-subtle px-2 py-2"
          role="listbox"
          aria-label={t('person.switchAction')}
        >
          {persons.map((p) => (
            <li key={p.id}>
              <button
                type="button"
                role="option"
                aria-selected={p.id === picker.data?.current_person_id}
                disabled={switchPerson.isPending}
                onClick={() => switchPerson.mutate(p.id)}
                className="flex w-full items-center gap-3 rounded-sm px-2 py-2.5 text-left hover:bg-bg-canvas"
              >
                <Avatar initials={initials(p, 1)} seed={p.id} size={32} />
                <span className="type-body text-text-primary">{p.full_name}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      <nav aria-label={t('mobile.more')} className="min-h-0 flex-1 overflow-y-auto">
        <Link
          to="/contacts/personal"
          onClick={onClose}
          className="flex min-h-[48px] items-center gap-3 border-b border-border-default px-4 py-3 text-text-primary hover:bg-bg-subtle"
        >
          <Users size={20} aria-hidden="true" />
          <span className="type-body flex-1">{t('rail.contacts')}</span>
          <ChevronRight size={18} className="text-text-tertiary" aria-hidden="true" />
        </Link>
        <Link
          to="/settings"
          onClick={onClose}
          className="flex min-h-[48px] items-center gap-3 border-b border-border-default px-4 py-3 text-text-primary hover:bg-bg-subtle"
        >
          <Settings size={20} aria-hidden="true" />
          <span className="type-body flex-1">{t('rail.settings')}</span>
          <ChevronRight size={18} className="text-text-tertiary" aria-hidden="true" />
        </Link>
        <button
          type="button"
          onClick={() => {
            onClose();
            open('notifications');
          }}
          className="flex min-h-[48px] w-full items-center gap-3 border-b border-border-default px-4 py-3 text-left text-text-primary hover:bg-bg-subtle"
        >
          <Bell size={20} aria-hidden="true" />
          <span className="type-body flex-1">{t('rail.notifications')}</span>
          <ChevronRight size={18} className="text-text-tertiary" aria-hidden="true" />
        </button>
        {canSwitch ? (
          <button
            type="button"
            onClick={() => setSwitchOpen(true)}
            className="flex min-h-[48px] w-full items-center gap-3 border-b border-border-default px-4 py-3 text-left text-text-primary hover:bg-bg-subtle"
          >
            <UserCheck size={20} aria-hidden="true" />
            <span className="min-w-0 flex-1">
              <span className="type-body block">{t('person.switchAction')}</span>
              {others.length ? (
                <span className="type-caption text-text-secondary">{others.map((p) => p.first_name).join(' · ')}</span>
              ) : null}
            </span>
            <ChevronRight size={18} className="text-text-tertiary" aria-hidden="true" />
          </button>
        ) : null}
        <div className="flex flex-col gap-2 border-b border-border-default px-4 py-3">
          <div className="flex items-center gap-3">
            <Moon size={20} aria-hidden="true" className="text-text-primary" />
            <span className="type-body text-text-primary">{t('prefs.theme')}</span>
          </div>
          <div
            role="radiogroup"
            aria-label={t('prefs.theme')}
            className="ml-8 flex flex-wrap gap-1.5"
            data-testid="m18-theme"
          >
            {THEME_OPTS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                role="radio"
                aria-checked={theme === opt.value}
                onClick={() => setTheme(opt.value)}
                className={`type-caption rounded-full px-2.5 py-1.5 ${
                  theme === opt.value
                    ? 'bg-brand-primary-600 text-text-on-primary'
                    : 'bg-bg-muted text-text-secondary hover:bg-bg-subtle'
                }`}
              >
                {t(opt.labelKey)}
              </button>
            ))}
          </div>
        </div>
        <button
          type="button"
          onClick={() => {
            onClose();
            open('about');
          }}
          className="flex min-h-[48px] w-full items-center gap-3 border-b border-border-default px-4 py-3 text-left text-text-primary hover:bg-bg-subtle"
        >
          <CircleHelp size={20} aria-hidden="true" />
          <span className="type-body flex-1">{t('rail.about')}</span>
          <ChevronRight size={18} className="text-text-tertiary" aria-hidden="true" />
        </button>
        <button
          type="button"
          onClick={onLogout}
          className="flex min-h-[48px] w-full items-center gap-3 px-4 py-3 text-left text-cat-complaint hover:bg-bg-subtle"
        >
          <LogOut size={20} aria-hidden="true" />
          <span className="type-body">{t('rail.logout')}</span>
        </button>
      </nav>
    </div>
  );
}
