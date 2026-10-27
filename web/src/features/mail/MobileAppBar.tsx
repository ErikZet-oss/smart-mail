import { ChevronDown, Menu, Search } from 'lucide-react';
import { useTranslation } from 'react-i18next';

type Props = {
  title: string;
  onOpenFolders: () => void;
  onSearch: () => void;
};

/** M1 app bar: ☰ folders, title (+ chevron → drawer), search. Compose is the FAB. */
export function MobileAppBar({ title, onOpenFolders, onSearch }: Props) {
  const { t } = useTranslation();
  return (
    <header
      data-testid="mobile-app-bar"
      className="flex h-12 shrink-0 items-center gap-1 border-b border-border-default bg-bg-canvas px-1 pt-[env(safe-area-inset-top)]"
    >
      <button
        type="button"
        onClick={onOpenFolders}
        aria-label={t('folders.label')}
        className="flex size-11 items-center justify-center rounded-sm text-text-primary hover:bg-bg-subtle"
      >
        <Menu size={22} />
      </button>
      <button
        type="button"
        onClick={onOpenFolders}
        className="flex min-w-0 flex-1 items-center gap-1 rounded-sm px-1 text-left hover:bg-bg-subtle"
        aria-label={t('folders.label')}
      >
        <h1 className="type-heading min-w-0 truncate text-text-primary">{title}</h1>
        <ChevronDown size={16} className="shrink-0 text-text-secondary" aria-hidden="true" />
      </button>
      <button
        type="button"
        onClick={onSearch}
        aria-label={t('system.search')}
        className="flex size-11 items-center justify-center rounded-sm text-text-primary hover:bg-bg-subtle"
      >
        <Search size={20} />
      </button>
    </header>
  );
}
