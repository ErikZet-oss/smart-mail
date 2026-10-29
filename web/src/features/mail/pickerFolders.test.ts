import { describe, expect, it } from 'vitest';
import type { Folder } from './mailApi';
import { pickerFolders } from './pickerFolders';

const f = (name: string, special: Folder['special_use'] = null, depth = 0, selectable = true): Folder => ({
  id: name,
  name,
  label: name.split('/').pop() ?? name,
  parent_id: null,
  depth,
  special_use: special,
  unread: 0,
  total: 0,
  selectable,
});

describe('#96 pickerFolders', () => {
  it('Roundcube order: special folders, Archív, then customer folders alphabetically', () => {
    const out = pickerFolders([
      f('Trenčín'),
      f('Trash', 'trash'),
      f('Dodávatelia'),
      f('Archív'),
      f('Sent', 'sent'),
      f('INBOX', 'inbox'),
      f('Junk', 'junk'),
      f('Drafts', 'drafts'),
      f('Faktúry/2026', null, 1),
      f('Faktúry'),
      f('Čakajúce'),
    ]);
    expect(out.map((x) => x.name)).toEqual([
      'INBOX',
      'Drafts',
      'Sent',
      'Junk',
      'Trash',
      'Archív',
      'Čakajúce',
      'Dodávatelia',
      'Faktúry',
      'Faktúry/2026',
      'Trenčín',
    ]);
  });

  it('leaves out folders that cannot hold messages', () => {
    expect(pickerFolders([f('INBOX', 'inbox'), f('Shared', null, 0, false)]).map((x) => x.name)).toEqual(['INBOX']);
  });
});
