import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  dispatchMailShortcut,
  isEditable,
  matchShortcut,
  modalOpen,
  registerMailShortcuts,
  type MailShortcutHandlers,
} from './shortcuts';

const key = (k: string, mods: Partial<KeyboardEvent> = {}) => ({
  key: k,
  shiftKey: false,
  ctrlKey: false,
  altKey: false,
  metaKey: false,
  ...mods,
});

describe('#93 matchShortcut', () => {
  it.each([
    [key('Delete'), 'delete'],
    [key('Delete', { shiftKey: true }), 'purge'],
    [key('ArrowDown'), 'down'],
    [key('ArrowUp'), 'up'],
    [key('Enter'), 'open'],
    [key('a', { ctrlKey: true }), 'selectAll'],
    [key('u'), 'unread'],
    [key('!', { shiftKey: true }), 'junk'],
    [key('r'), 'reply'],
    [key('R', { shiftKey: true }), 'replyAll'],
    [key('f'), 'forward'],
    [key('l'), 'moveTo'],
    [key('c'), 'compose'],
    [key('/'), 'search'],
    [key('?', { shiftKey: true }), 'help'],
  ])('%o → %s', (e, id) => {
    expect(matchShortcut(e)).toBe(id);
  });

  it.each([key('a'), key('e'), key('['), key('Delete', { altKey: true }), key('u', { metaKey: true })])(
    'ignores %o',
    (e) => {
      expect(matchShortcut(e)).toBeNull();
    },
  );
});

describe('#93 typing and dialogs', () => {
  it('treats inputs, textareas and contenteditable (TipTap) as typing', () => {
    const input = document.createElement('input');
    const area = document.createElement('textarea');
    const editor = document.createElement('div');
    editor.setAttribute('contenteditable', 'true'); // what TipTap renders
    document.body.append(editor);
    expect(isEditable(input)).toBe(true);
    expect(isEditable(area)).toBe(true);
    expect(isEditable(editor)).toBe(true);
    expect(isEditable(document.body)).toBe(false);
    editor.remove();
  });

  it('sees an open modal', () => {
    expect(modalOpen()).toBe(false);
    const dialog = document.createElement('div');
    dialog.setAttribute('aria-modal', 'true');
    document.body.append(dialog);
    expect(modalOpen()).toBe(true);
    dialog.remove();
  });
});

describe('#93 mail shortcut registry', () => {
  let unregister: (() => void) | null = null;
  afterEach(() => unregister?.());

  const handlers = (readOnly: boolean): MailShortcutHandlers => ({
    readOnly,
    delete: vi.fn(),
    purge: vi.fn(),
    down: vi.fn(),
  });

  it('Delete and Shift+Delete run the screen handlers (bulk delete / purge confirm)', () => {
    const h = handlers(false);
    unregister = registerMailShortcuts(() => h);
    expect(dispatchMailShortcut('delete')).toBe(true);
    expect(dispatchMailShortcut('purge')).toBe(true);
    expect(h.delete).toHaveBeenCalledOnce();
    expect(h.purge).toHaveBeenCalledOnce();
  });

  it('read-only: action keys do nothing, moving in the list still works', () => {
    const h = handlers(true);
    unregister = registerMailShortcuts(() => h);
    expect(dispatchMailShortcut('delete')).toBe(false);
    expect(dispatchMailShortcut('purge')).toBe(false);
    expect(dispatchMailShortcut('down')).toBe(true);
    expect(h.delete).not.toHaveBeenCalled();
    expect(h.down).toHaveBeenCalledOnce();
  });

  it('nothing registered (not on the mail screen): the key is left alone', () => {
    expect(dispatchMailShortcut('delete')).toBe(false);
  });
});
