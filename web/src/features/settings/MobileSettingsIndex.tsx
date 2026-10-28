import {
  ArrowLeft,
  ChevronRight,
  CircleUserRound,
  Clock,
  Folder,
  ListFilter,
  MessageSquare,
  Monitor,
  Shield,
  Sparkles,
  User,
  Users,
  type LucideIcon,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

/** Mobile-editable rows (SETTINGS_SPEC §M9). Notifikácie (08) wait for later phases. */
const MOBILE_SECTIONS: { to: string; titleKey: string; hintKey?: string; icon: LucideIcon }[] = [
  {
    to: '/settings/preferences',
    titleKey: 'settings.mobile.prefs',
    hintKey: 'settings.mobile.prefsHint',
    icon: ListFilter,
  },
  { to: '/settings/identity/profile', titleKey: 'settings.profile.title', icon: User },
  {
    to: '/settings/responses',
    titleKey: 'settings.mobile.responses',
    hintKey: 'settings.mobile.responsesHint',
    icon: MessageSquare,
  },
  { to: '/settings/vacation', titleKey: 'settings.mobile.vacation', icon: Clock },
  { to: '/settings/ai', titleKey: 'settingsAi.title', icon: Sparkles },
  {
    to: '/settings/security',
    titleKey: 'settings.mobile.security',
    hintKey: 'settings.mobile.securityHint',
    icon: Shield,
  },
];

const DESKTOP_ONLY: { titleKey: string; icon: LucideIcon }[] = [
  { titleKey: 'settings.mobile.folders', icon: Folder },
  { titleKey: 'settings.mobile.identities', icon: CircleUserRound },
  { titleKey: 'settings.mobile.filters', icon: ListFilter },
  { titleKey: 'settings.mobile.admin', icon: Users },
];

type Props = { onBack?: () => void };

/** M9 Nastavenia list — mobile-only index (SETTINGS_SPEC §M9). */
export function MobileSettingsIndex({ onBack }: Props) {
  const { t } = useTranslation();
  return (
    <div className="flex h-full min-h-0 flex-col bg-bg-canvas" data-testid="mobile-settings-index">
      <header className="flex h-12 shrink-0 items-center gap-1 border-b border-border-default px-1">
        {onBack ? (
          <button
            type="button"
            onClick={onBack}
            aria-label={t('system.back')}
            className="flex size-11 items-center justify-center rounded-sm text-text-primary hover:bg-bg-subtle"
          >
            <ArrowLeft size={22} />
          </button>
        ) : (
          <span className="w-11" aria-hidden="true" />
        )}
        <h1 className="type-heading min-w-0 flex-1 truncate text-text-primary">{t('settings.title')}</h1>
      </header>
      <ul className="min-h-0 flex-1 overflow-y-auto">
        {MOBILE_SECTIONS.map((item) => (
          <li key={item.to}>
            <Link
              to={item.to}
              className="flex min-h-[52px] items-center gap-3 border-b border-border-default px-4 py-2.5 text-text-primary hover:bg-bg-subtle"
            >
              <item.icon size={20} className="shrink-0 text-text-secondary" aria-hidden="true" />
              <span className="min-w-0 flex-1">
                <span className="type-body block">{t(item.titleKey)}</span>
                {item.hintKey ? (
                  <span className="type-caption block font-normal text-text-secondary">{t(item.hintKey)}</span>
                ) : null}
              </span>
              <ChevronRight size={18} className="shrink-0 text-text-tertiary" aria-hidden="true" />
            </Link>
          </li>
        ))}
        <li className="type-micro bg-bg-subtle px-4 pb-2 pt-4 uppercase text-text-secondary">
          {t('settings.mobile.desktopOnly')}
        </li>
        {DESKTOP_ONLY.map((item) => (
          <li
            key={item.titleKey}
            className="flex min-h-[52px] items-center gap-3 border-b border-border-default px-4 py-2.5 text-text-secondary"
          >
            <item.icon size={20} className="shrink-0" aria-hidden="true" />
            <span className="min-w-0 flex-1">
              <span className="type-body block">{t(item.titleKey)}</span>
              <span className="type-caption block font-normal">{t('settings.mobile.editOnDesktop')}</span>
            </span>
            <Monitor size={18} className="shrink-0" aria-hidden="true" />
          </li>
        ))}
      </ul>
    </div>
  );
}
