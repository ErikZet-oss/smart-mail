import { CircleHelp, LogOut, Settings } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

type Props = { open: boolean; onClose: () => void; onLogout: () => void };

/** Interim Viac sheet for 1h-a (full M18 arrives in 1h-b). */
export function MobileMoreSheet({ open, onClose, onLogout }: Props) {
  const { t } = useTranslation();
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex flex-col justify-end bg-bg-overlay sm:hidden"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('mobile.more')}
        data-testid="mobile-more-sheet"
        className="rounded-t-lg bg-bg-canvas pb-[env(safe-area-inset-bottom)] shadow-e3"
      >
        <div className="mx-auto mt-2 mb-3 h-1 w-10 rounded-full bg-border-strong" aria-hidden="true" />
        <Link
          to="/settings/general"
          onClick={onClose}
          className="flex min-h-[48px] items-center gap-3 px-4 py-3 text-text-primary hover:bg-bg-subtle"
        >
          <Settings size={20} aria-hidden="true" />
          <span className="type-body">{t('rail.settings')}</span>
        </Link>
        <button
          type="button"
          disabled
          title={t('common.comingSoon')}
          className="flex min-h-[48px] w-full items-center gap-3 px-4 py-3 text-left text-text-tertiary"
        >
          <CircleHelp size={20} aria-hidden="true" />
          <span className="type-body">{t('rail.about')}</span>
        </button>
        <button
          type="button"
          onClick={() => {
            onClose();
            onLogout();
          }}
          className="flex min-h-[48px] w-full items-center gap-3 px-4 py-3 text-left text-cat-complaint hover:bg-bg-subtle"
        >
          <LogOut size={20} aria-hidden="true" />
          <span className="type-body">{t('rail.logout')}</span>
        </button>
        <button type="button" onClick={onClose} className="type-small w-full px-4 py-3 text-text-secondary">
          {t('common.close')}
        </button>
      </div>
    </div>
  );
}
