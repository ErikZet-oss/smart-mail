import type { QueryClient, QueryKey } from '@tanstack/react-query';
import { foldersKey, type BulkAction, type FoldersView, type MessagesList } from './mailApi';

/** Actions that take the message out of the folder on screen (#89). */
export const REMOVING_ACTIONS: ReadonlySet<BulkAction> = new Set(['delete', 'purge', 'junk', 'archive', 'move']);

/**
 * #89: show the result of a toolbar action at once, before the server answers. Updates every cached message list of
 * the mailbox and the folder counts. Returns a rollback that puts the snapshots back (request failed).
 */
export function applyActionLocally(
  client: QueryClient,
  mailbox: string,
  ids: readonly string[],
  action: BulkAction,
): () => void {
  const idSet = new Set(ids);
  const snapshots: [QueryKey, unknown][] = [];
  const lists = [
    ...client.getQueriesData<MessagesList>({ queryKey: ['mail', 'messages', mailbox] }),
    ...client.getQueriesData<MessagesList>({ queryKey: ['mail', 'ai-view', mailbox] }),
  ];
  // folder id → change of its total and unread count
  const perFolder = new Map<string, { total: number; unread: number }>();
  const bump = (folderId: string, total: number, unread: number) => {
    const cur = perFolder.get(folderId) ?? { total: 0, unread: 0 };
    perFolder.set(folderId, { total: cur.total + total, unread: cur.unread + unread });
  };
  const counted = new Set<string>();
  const removing = REMOVING_ACTIONS.has(action);

  for (const [key, data] of lists) {
    if (!data) continue;
    let next: MessagesList | null = null;
    const hits = data.messages.filter((m) => idSet.has(m.id));
    for (const m of hits) {
      if (counted.has(m.id)) continue;
      counted.add(m.id);
      if (removing) bump(m.folder_id, -1, m.seen ? 0 : -1);
      else if (action === 'mark_seen' && !m.seen) bump(m.folder_id, 0, -1);
      else if (action === 'mark_unseen' && m.seen) bump(m.folder_id, 0, 1);
    }
    if (removing) {
      const messages = data.messages.filter((m) => !idSet.has(m.id));
      const threads = data.threads.filter((th) => !idSet.has(th.id) && !idSet.has(th.latest_message_id ?? ''));
      const removed = data.messages.length - messages.length + (data.threads.length - threads.length);
      if (removed) next = { ...data, messages, threads, total: Math.max(0, data.total - removed) };
    } else if (hits.length && action !== 'done') {
      const patch =
        action === 'mark_seen' || action === 'mark_unseen'
          ? { seen: action === 'mark_seen' }
          : action === 'flag' || action === 'unflag'
            ? { flagged: action === 'flag' }
            : null;
      if (patch) next = { ...data, messages: data.messages.map((m) => (idSet.has(m.id) ? { ...m, ...patch } : m)) };
    }
    if (next) {
      snapshots.push([key, data]);
      client.setQueryData(key, next);
    }
  }

  const view = client.getQueryData<FoldersView>(foldersKey(mailbox));
  if (view && perFolder.size) {
    snapshots.push([foldersKey(mailbox), view]);
    let unreadDelta = 0;
    client.setQueryData<FoldersView>(foldersKey(mailbox), {
      ...view,
      folders: view.folders.map((f) => {
        const d = perFolder.get(f.id);
        if (!d) return f;
        unreadDelta += d.unread;
        return { ...f, total: Math.max(0, f.total + d.total), unread: Math.max(0, f.unread + d.unread) };
      }),
      mailbox: { ...view.mailbox, unread: Math.max(0, view.mailbox.unread + unreadDelta) },
    });
  }

  return () => {
    for (const [key, data] of snapshots) client.setQueryData(key, data);
  };
}
