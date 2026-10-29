import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { Menu, type MenuEntry } from '../../components/Menu';
import { MOBILE_QUERY, useMediaQuery } from '../../lib/useMediaQuery';
import { fetchFolders, foldersKey, type Folder } from './mailApi';
import { pickerFolders } from './pickerFolders';
import { useFolderLabel } from './useFolderLabel';

type Props = {
  mailbox: string;
  mode: 'move' | 'copy';
  /** The folder the messages are in — shown, but cannot be picked. */
  currentFolderId: string | null;
  at: { x: number; y: number };
  onPick: (folder: Folder) => void;
  onClose: () => void;
};

/** Folder list for Presunúť do… / Kopírovať do…; on a phone it docks at the bottom like a sheet (M1/M2). */
export function FolderPicker({ mailbox, mode, currentFolderId, at, onPick, onClose }: Props) {
  const { t } = useTranslation();
  const labelOf = useFolderLabel();
  const mobile = useMediaQuery(MOBILE_QUERY);
  const view = useQuery({ queryKey: foldersKey(mailbox), queryFn: () => fetchFolders(mailbox) });
  const title = t(mode === 'move' ? 'mail.moveTo.move' : 'mail.moveTo.copy');
  const entries: MenuEntry[] = [
    { kind: 'label', id: 'title', label: title },
    ...pickerFolders(view.data?.folders ?? []).map((folder): MenuEntry => ({
      kind: 'item',
      id: folder.id,
      label: `${' '.repeat(Math.min(folder.depth, 4))}${labelOf(folder)}`,
      disabled: folder.id === currentFolderId,
      onSelect: () => onPick(folder),
    })),
  ];
  const width = mobile ? window.innerWidth - 16 : 260; // Menu keeps an 8 px margin on each side
  return (
    <Menu
      label={title}
      entries={entries}
      at={mobile ? { x: 0, y: window.innerHeight } : at}
      width={width}
      onClose={() => onClose()}
    />
  );
}
