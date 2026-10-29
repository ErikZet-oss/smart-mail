import { QueryClient } from '@tanstack/react-query';
import { describe, expect, it } from 'vitest';
import { foldersKey, messagesKey, type FoldersView, type MessageListItem, type MessagesList } from './mailApi';
import { applyActionLocally } from './optimistic';

const row = (id: string, seen: boolean): MessageListItem => ({
  id,
  thread_id: `t-${id}`,
  folder_id: 'inbox',
  uid: 1,
  subject: id,
  from_name: null,
  from_email: null,
  preview: null,
  received_at: null,
  sent_at: null,
  size: 1,
  seen,
  flagged: false,
  answered: false,
  has_attachments: false,
  thread_count: 1,
});

function setup() {
  const client = new QueryClient();
  const listKey = messagesKey('default', 'inbox', 1, 'all');
  const list: MessagesList = {
    mode: 'list',
    total: 3,
    page: 1,
    page_size: 50,
    messages: [row('a', false), row('b', true), row('c', false)],
    threads: [],
    prefs: {} as MessagesList['prefs'],
  };
  const view = {
    mailbox: { id: 'mb', email: 'x@smartmail.test', unread: 2, sync_state: 'ok' },
    folders: [
      {
        id: 'inbox',
        name: 'INBOX',
        label: 'Doručená pošta',
        parent_id: null,
        depth: 0,
        special_use: 'inbox',
        unread: 2,
        total: 3,
        selectable: true,
      },
    ],
    quota: null,
    sync: { state: 'ok', error: null, last_synced_at: null },
  } as FoldersView;
  client.setQueryData(listKey, list);
  client.setQueryData(foldersKey('default'), view);
  return { client, listKey, list, view };
}

describe('#89 optimistic toolbar actions', () => {
  it('delete removes the rows and lowers the folder counts at once', () => {
    const { client, listKey } = setup();
    applyActionLocally(client, 'default', ['a', 'b'], 'delete');
    const list = client.getQueryData<MessagesList>(listKey);
    expect(list?.messages.map((m) => m.id)).toEqual(['c']);
    expect(list?.total).toBe(1);
    const view = client.getQueryData<FoldersView>(foldersKey('default'));
    expect(view?.folders[0]).toMatchObject({ total: 1, unread: 1 });
    expect(view?.mailbox.unread).toBe(1);
  });

  it('rollback restores the list and the counts when the request fails', () => {
    const { client, listKey, list, view } = setup();
    const rollback = applyActionLocally(client, 'default', ['a'], 'archive');
    rollback();
    expect(client.getQueryData(listKey)).toEqual(list);
    expect(client.getQueryData(foldersKey('default'))).toEqual(view);
  });

  it('mark_seen and flag change the row icon without removing it', () => {
    const { client, listKey } = setup();
    applyActionLocally(client, 'default', ['a'], 'mark_seen');
    applyActionLocally(client, 'default', ['a'], 'flag');
    const a = client.getQueryData<MessagesList>(listKey)?.messages.find((m) => m.id === 'a');
    expect(a).toMatchObject({ seen: true, flagged: true });
    expect(client.getQueryData<FoldersView>(foldersKey('default'))?.folders[0]?.unread).toBe(1);
  });
});
