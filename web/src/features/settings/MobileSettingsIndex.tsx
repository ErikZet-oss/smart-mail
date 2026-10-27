import { ArrowLeft, ChevronRight, Monitor } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

/** Mobile-editable rows (SETTINGS_SPEC §M9). Notifikácie (08) wait for later phases. */
const MOBILE_SECTIONS: { to: string; titleKey: string; hintKey?: string }[] = [
  { to: '/settings/preferences', titleKey: 'settings.mobile.prefs', hintKey: 'settings.mobile.prefsHint' },
  { to: '/settings/identity/profile', titleKey: 'settings.profile.title' },
  { to: '/settings/responses', titleKey: 'settings.mobile.responses', hintKey: 'settings.mobile.responsesHint' },
  { to: '/settings/vacation', titleKey: 'settings.mobile.vacation' },
  { to: '/settings/ai', titleKey: 'settingsAi.title' },
  { to: '/settings/security', titleKey: 'settings.mobile.security', hintKey: 'settings.mobile.securityHint' },
];

const DESKTOP_ONLY: { titleKey: string }[] = [
  { titleKey: 'settings.mobile.folders' },
  { titleKey: 'settings.mobile.identities' },
  { titleKey: 'settings.mobile.filters' },
  { titleKey: 'settings.mobile.admin' },
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
              className="flex min-h-[52px] items-center gap-3 border-b border-border-subtle px-4 py-3 text-text-primary hover:bg-bg-subtle"
            >
              <span className="min-w-0 flex-1">
                <span className="type-body block">{t(item.titleKey)}</span>
                {item.hintKey ? <span className="type-caption text-text-secondary">{t(item.hintKey)}</span> : null}
              </span>
              <ChevronRight size={18} className="shrink-0 text-text-tertiary" aria-hidden="true" />
            </Link>
          </li>
        ))}
        <li className="type-caption bg-bg-muted px-4 py-2 text-text-secondary">{t('settings.mobile.desktopOnly')}</li>
        {DESKTOP_ONLY.map((item) => (
          <li
            key={item.titleKey}
            className="flex min-h-[52px] items-center gap-3 border-b border-border-subtle px-4 py-3 text-text-tertiary"
          >
            <span className="min-w-0 flex-1">
              <span className="type-body block">{t(item.titleKey)}</span>
              <span className="type-caption">{t('settings.mobile.editOnDesktop')}</span>
            </span>
            <Monitor size={18} className="shrink-0" aria-hidden="true" />
          </li>
        ))}
      </ul>
    </div>
  );
}
