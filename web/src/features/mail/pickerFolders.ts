import type { Folder } from './mailApi';

const SPECIAL_ORDER = ['inbox', 'drafts', 'sent', 'junk', 'trash'];
const ARCHIVE_NAMES = new Set(['archív', 'archive']);

/**
 * Destinations of Presunúť do… / Kopírovať do… (#96), Roundcube order: the special folders, Archív, then the
 * customer folders alphabetically (sub-folders follow their parent because the full IMAP name is compared).
 */
export function pickerFolders(folders: readonly Folder[]): Folder[] {
  const rank = (f: Folder) => {
    const special = f.special_use ? SPECIAL_ORDER.indexOf(f.special_use) : -1;
    if (special >= 0) return special;
    if (f.depth === 0 && ARCHIVE_NAMES.has(f.name.toLowerCase())) return SPECIAL_ORDER.length;
    return SPECIAL_ORDER.length + 1;
  };
  return folders
    .filter((f) => f.selectable)
    .slice()
    .sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name, 'sk'));
}
