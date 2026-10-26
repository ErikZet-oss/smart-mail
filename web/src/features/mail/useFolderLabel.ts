import { useTranslation } from 'react-i18next';

import type { Folder } from './mailApi';

/** SK name of a folder: special folders by SPECIAL-USE (Roundcube SK names), own folders as on the server (D21). */
export function useFolderLabel(): (folder: Folder) => string {
  const { t } = useTranslation();
  return (folder) => (folder.special_use ? t(`folders.special.${folder.special_use}`) : folder.label);
}
