import { QueryClient } from '@tanstack/react-query';
import { describe, expect, it } from 'vitest';

import type { ListPrefs } from '../prefs/prefsApi';
import {
  applyAttachmentFlagLocally,
  foldersKey,
  markSeenLocally,
  messagesKey,
  type FoldersView,
  type MessageDetail,
  type MessagesList,
} from './mailApi';

function list(seen: boolean): MessagesList {
  return {
    mode: 'list',
    total: 1,
    page: 1,
    page_size: 50,
    threads: [],
    prefs: {} as ListPrefs,
    messages: [
      {
        id: 'm-1',
        thread_id: 't-1',
        folder_id: 'f-in',
        seen,
      } as MessagesList['messages'][number],
    ],
  };
}

function folders(unread: number): FoldersView {
  return {
    mailbox: { id: 'mb', email: 'eshop@smartmail.test', unread, sync_state: 'ok' },
    folders: [
      {
        id: 'f-in',
        name: 'INBOX',
        label: 'Doručená pošta',
        parent_id: null,
        depth: 0,
        special_use: 'inbox',
        unread,
        total: 5,
        selectable: true,
      },
    ],
    quota: null,
    sync: { state: 'ok', error: null, last_synced_at: null },
  };
}

describe('markSeenLocally (pilot: "prečítané" must show at once)', () => {
  it('marks the row read and lowers the folder and mailbox unread counts', () => {
    const qc = new QueryClient();
    const key = [...messagesKey('default', 'f-in', 1, 'all'), ''];
    qc.setQueryData(key, list(false));
    qc.setQueryData(foldersKey('default'), folders(3));
    markSeenLocally(qc, 'default', 'm-1', 't-1', 'f-in');
    expect(qc.getQueryData<MessagesList>(key)?.messages[0]?.seen).toBe(true);
    const view = qc.getQueryData<FoldersView>(foldersKey('default'));
    expect(view?.folders[0]?.unread).toBe(2);
    expect(view?.mailbox.unread).toBe(2);
  });

  it('does not count an already read message twice', () => {
    const qc = new QueryClient();
    const key = [...messagesKey('default', 'f-in', 1, 'all'), ''];
    qc.setQueryData(key, list(true));
    qc.setQueryData(foldersKey('default'), folders(3));
    markSeenLocally(qc, 'default', 'm-1', 't-1', 'f-in');
    expect(qc.getQueryData<FoldersView>(foldersKey('default'))?.folders[0]?.unread).toBe(3);
  });

  it('lowers the thread unread count in Konverzácie mode', () => {
    const qc = new QueryClient();
    const key = [...messagesKey('default', 'f-in', 1, 'all'), ''];
    qc.setQueryData<MessagesList>(key, {
      ...list(false),
      mode: 'conversations',
      messages: [],
      threads: [{ id: 't-1', unread_count: 2 } as MessagesList['threads'][number]],
    });
    qc.setQueryData(foldersKey('default'), folders(3));
    markSeenLocally(qc, 'default', 'm-1', 't-1', 'f-in');
    expect(qc.getQueryData<MessagesList>(key)?.threads[0]?.unread_count).toBe(1);
    expect(qc.getQueryData<FoldersView>(foldersKey('default'))?.folders[0]?.unread).toBe(2);
  });
});

describe('applyAttachmentFlagLocally (review #67: paperclip right after the first open)', () => {
  const withPaperclip = (has: boolean): MessagesList => {
    const base = list(true);
    return { ...base, messages: base.messages.map((m) => ({ ...m, has_attachments: has })) };
  };
  const detail = (attachments: { is_inline: boolean }[]) =>
    ({ id: 'm-1', thread_id: 't-1', attachments }) as unknown as MessageDetail;

  it('the list row gets has_attachments=true from the detail, without a refetch', () => {
    const qc = new QueryClient();
    const key = messagesKey('default', 'f-in', 1, 'all');
    qc.setQueryData(key, withPaperclip(false));
    applyAttachmentFlagLocally(qc, 'default', detail([{ is_inline: false }]));
    expect(qc.getQueryData<MessagesList>(key)?.messages[0]?.has_attachments).toBe(true);
  });

  it('a signature logo shown inline is not a paperclip', () => {
    const qc = new QueryClient();
    const key = messagesKey('default', 'f-in', 1, 'all');
    qc.setQueryData(key, withPaperclip(true));
    applyAttachmentFlagLocally(qc, 'default', detail([{ is_inline: true }]));
    expect(qc.getQueryData<MessagesList>(key)?.messages[0]?.has_attachments).toBe(false);
  });
});
