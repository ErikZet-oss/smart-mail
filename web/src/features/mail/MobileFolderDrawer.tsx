import { X } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { FolderColumn } from './FolderColumn';
import type { AiCategory, FoldersView } from './mailApi';

type Props = {
  open: boolean;
  onClose: () => void;
  mailboxRef: string;
  view: FoldersView;
  activeRef: string;
  readOnly: boolean;
  classic?: boolean;
  aiCategories?: AiCategory[];
  activeCategory?: string | null;
};

/** M2 Priečinky — left drawer over the mobile list. */
export function MobileFolderDrawer({
  open,
  onClose,
  mailboxRef,
  view,
  activeRef,
  readOnly,
  classic = false,
  aiCategories = [],
  activeCategory = null,
}: Props) {
  const { t } = useTranslation();
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-40 flex sm:hidden"
      role="presentation"
      data-testid="folder-drawer"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="absolute inset-0 bg-bg-overlay" aria-hidden="true" onClick={onClose} />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('folders.label')}
        className="relative z-10 flex h-full w-[min(100%,320px)] flex-col bg-bg-canvas shadow-e3"
      >
        <header className="flex h-12 shrink-0 items-center justify-between border-b border-border-default px-3">
          <h2 className="type-heading text-text-primary">{t('folders.label')}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close')}
            className="rounded-sm p-2 text-text-secondary hover:bg-bg-subtle"
          >
            <X size={20} />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-hidden" onClick={onClose}>
          <FolderColumn
            mailboxRef={mailboxRef}
            view={view}
            activeRef={activeRef}
            readOnly={readOnly}
            classic={classic}
            aiCategories={aiCategories}
            activeCategory={activeCategory}
          />
        </div>
      </div>
    </div>
  );
}
