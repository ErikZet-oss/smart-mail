import { CircleHelp, Mail, Moon, Power, Settings, SquarePen, Sun, Users } from 'lucide-react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import { HOME } from '../../app/routes';
import { formatCount } from '../../features/mail/mailApi';
import { PersonChip, type ChipExtra } from '../../features/persons/PersonChip';
import { useTheme } from '../../features/prefs/ThemeProvider';
import { useMediaQuery } from '../../lib/useMediaQuery';
import { Logo } from '../Logo';

export type RailSection = 'mail' | 'settings';

/** Below 820 px height Tmavý režim and O systéme move into the PersonChip menu (G1). */
export const LOW_RAIL_QUERY = '(max-height: 819.98px)';

type ItemProps = {
  icon: ReactNode;
  label: string;
  to?: string;
  active?: boolean;
  badge?: number;
  tall?: boolean;
  tone?: 'default' | 'compose' | 'logout';
  hint?: string;
  shortcut?: string;
  onClick?: () => void;
};

const LABEL_TONE = {
  default: '',
  compose: 'text-brand-primary-400',
  logout: 'text-cat-complaint',
} as const;

/** Figma `RailItem`: 20 px icon over a micro label, active = rail-active + 3 px primary-400 bar. */
function RailItem({
  icon,
  label,
  to,
  active,
  badge,
  tall = true,
  tone = 'default',
  hint,
  shortcut,
  onClick,
}: ItemProps) {
  const { t } = useTranslation();
  const disabled = !to && !onClick;
  const className = `relative flex w-[72px] shrink-0 flex-col items-center justify-center gap-1 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-brand-primary-500 ${
    tall ? 'h-14' : 'h-[52px]'
  } ${active ? 'bg-bg-rail-active text-text-on-rail-active' : 'text-text-on-rail'} ${
    disabled ? 'cursor-not-allowed opacity-50' : 'hover:bg-bg-rail-active hover:text-text-on-rail-active'
  }`;
  const title = disabled ? t('common.comingSoon') : shortcut ? `${hint ?? label} (${shortcut})` : hint;
  const body = (
    <>
      {active ? <span aria-hidden="true" className="absolute inset-y-0 left-0 w-[3px] bg-brand-primary-400" /> : null}
      <span
        aria-hidden="true"
        className={tone === 'logout' ? 'text-cat-complaint' : tone === 'compose' ? 'text-brand-primary-400' : ''}
      >
        {icon}
      </span>
      <span className={`type-micro w-[68px] truncate text-center ${LABEL_TONE[tone]}`}>{label}</span>
      {badge ? (
        <span
          aria-hidden="true"
          className="type-micro absolute left-10 top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-danger-600 px-1 text-text-on-primary"
        >
          {formatCount(badge)}
        </span>
      ) : null}
    </>
  );
  const name = badge ? t('rail.withUnread', { label, count: badge }) : label;
  if (to) {
    return (
      <Link to={to} aria-current={active ? 'page' : undefined} aria-label={name} title={title} className={className}>
        {body}
      </Link>
    );
  }
  return (
    <button type="button" onClick={onClick} disabled={disabled} aria-label={name} title={title} className={className}>
      {body}
    </button>
  );
}

type Props = { section: RailSection; mailbox: string; unread: number; onLogout: () => void };

/** G1 rail (72 px, dark) in the Roundcube order; items of later phases are not shown yet (Dnes, Doklady, Asistent,
 * Notifikácie) or are visibly disabled until their milestone (Vytvoriť správu 1e, Kontakty 1g, O systéme 1h). */
export function Rail({ section, mailbox, unread, onLogout }: Props) {
  const { t } = useTranslation();
  const low = useMediaQuery(LOW_RAIL_QUERY);
  const { theme, toggleTheme, classic, setClassic } = useTheme();
  const systemDark =
    typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      ? window.matchMedia('(prefers-color-scheme: dark)').matches
      : false;
  const darkOn = theme === 'dark' || (theme === 'system' && systemDark);
  const extras: ChipExtra[] = [
    ...(low
      ? [
          {
            id: 'dark',
            label: t('rail.darkMode'),
            icon: darkOn ? <Sun size={16} /> : <Moon size={16} />,
            onSelect: toggleTheme,
          },
          { id: 'about', label: t('rail.about'), icon: <CircleHelp size={16} />, hint: t('common.comingSoon') },
        ]
      : []),
    {
      id: 'classic',
      label: t('rail.classic'),
      icon: <ListIcon />,
      onSelect: () => setClassic(!classic),
    },
  ];
  return (
    <nav
      aria-label={t('rail.label')}
      className="flex h-full w-[72px] shrink-0 flex-col overflow-y-auto overflow-x-hidden bg-bg-rail"
    >
      <Link
        to={HOME}
        aria-label={t('rail.home')}
        className="flex shrink-0 justify-center pb-2.5 pt-3.5 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-brand-primary-500"
      >
        <Logo width={52} tone="white" />
      </Link>
      <RailItem icon={<SquarePen size={20} />} label={t('rail.compose')} tone="compose" to="/compose" />
      <RailItem
        icon={<Mail size={20} />}
        label={t('rail.mail')}
        to={`/mail/${encodeURIComponent(mailbox)}/inbox`}
        active={section === 'mail'}
        badge={unread}
      />
      <RailItem icon={<Users size={20} />} label={t('rail.contacts')} />
      <RailItem
        icon={<Settings size={20} />}
        label={t('rail.settings')}
        to="/settings/general"
        active={section === 'settings'}
      />
      <div className="min-h-2 flex-1" />
      <PersonChip onLogout={onLogout} extras={extras} />
      {low ? null : (
        <>
          <RailItem
            icon={darkOn ? <Sun size={20} /> : <Moon size={20} />}
            label={t('rail.darkMode')}
            tall={false}
            onClick={toggleTheme}
          />
          <RailItem icon={<CircleHelp size={20} />} label={t('rail.about')} tall={false} />
        </>
      )}
      <RailItem icon={<Power size={20} />} label={t('rail.logout')} tall={false} tone="logout" onClick={onLogout} />
      <div className="h-1.5 shrink-0" />
    </nav>
  );
}

/** Tiny list glyph for Klasické zobrazenie (PersonChip menu) without a new Lucide import cycle. */
function ListIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      aria-hidden="true"
    >
      <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" />
    </svg>
  );
}
