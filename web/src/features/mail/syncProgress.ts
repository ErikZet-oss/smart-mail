import type { FoldersView } from './mailApi';

const COUNT = new Intl.NumberFormat('sk-SK');

/** "12 400 / 25 000" while a large first sync is still filling the local copy (#41); null when complete. */
export function firstSyncProgress(sync: FoldersView['sync'] | undefined): { loaded: string; total: string } | null {
  const loaded = sync?.loaded ?? 0;
  const total = sync?.total ?? 0;
  if (!sync || sync.state === 'error' || total === 0 || loaded >= total) return null;
  return { loaded: COUNT.format(loaded), total: COUNT.format(total) };
}
