import { Mail, Menu, Users } from 'lucide-react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

export type BottomSection = 'mail' | 'contacts' | 'more';

type ItemProps = {
  to?: string;
  onClick?: () => void;
  active?: boolean;
  icon: ReactNode;
  label: string;
};

function NavItem({ to, onClick, active, icon, label }: ItemProps) {
  const className = `flex min-h-[44px] min-w-0 flex-1 flex-col items-center justify-center gap-0.5 pt-1 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-brand-primary-500 ${
    active ? 'text-brand-primary-600' : 'text-text-secondary'
  }`;
  const body = (
    <>
      <span aria-hidden="true">{icon}</span>
      <span className="type-micro truncate">{label}</span>
    </>
  );
  if (to) {
    return (
      <Link to={to} aria-current={active ? 'page' : undefined} aria-label={label} className={className}>
        {body}
      </Link>
    );
  }
  return (
    <button type="button" onClick={onClick} aria-label={label} aria-pressed={active} className={className}>
      {body}
    </button>
  );
}

type Props = {
  section: BottomSection;
  mailbox?: string;
  unread?: number;
  onMore: () => void;
};

/**
 * M1 bottom nav — Phase 1 items only: E-mail, Kontakty, Viac.
 * Dnes / Doklady are not rendered (phases 5 / 4), same rule as W11.
 */
export function BottomNav({ section, mailbox = 'default', unread = 0, onMore }: Props) {
  const { t } = useTranslation();
  const mailIcon =
    unread > 0 ? (
      <span className="relative inline-flex">
        <Mail size={22} />
        <span className="absolute -right-2 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-danger-600 px-0.5 text-[10px] font-semibold text-text-on-primary">
          {unread > 99 ? '99+' : unread}
        </span>
      </span>
    ) : (
      <Mail size={22} />
    );
  return (
    <nav
      aria-label={t('mobile.bottomNav')}
      data-testid="bottom-nav"
      className="flex h-16 shrink-0 border-t border-border-default bg-bg-canvas pb-[env(safe-area-inset-bottom)]"
      style={{ minHeight: 'var(--layout-bottomnav)' }}
    >
      <NavItem
        to={`/mail/${encodeURIComponent(mailbox)}/inbox`}
        active={section === 'mail'}
        icon={mailIcon}
        label={t('rail.mail')}
      />
      <NavItem
        to="/contacts/personal"
        active={section === 'contacts'}
        icon={<Users size={22} />}
        label={t('rail.contacts')}
      />
      <NavItem onClick={onMore} active={section === 'more'} icon={<Menu size={22} />} label={t('mobile.more')} />
    </nav>
  );
}
