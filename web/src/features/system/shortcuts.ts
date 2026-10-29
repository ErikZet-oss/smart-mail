/**
 * UX_SPEC §6 keyboard shortcuts (#93): one central matcher + a registry for the mail screen.
 * `useGlobalShortcuts` owns the keydown listener; the mail screen only registers what each key does.
 */

export type MailShortcut =
  'up' | 'down' | 'open' | 'delete' | 'purge' | 'selectAll' | 'unread' | 'junk' | 'reply' | 'replyAll' | 'forward';

export type ShortcutId = 'help' | 'compose' | 'search' | MailShortcut;

type KeyLike = Pick<KeyboardEvent, 'key' | 'shiftKey' | 'ctrlKey' | 'altKey' | 'metaKey'>;

/** Shortcuts that change mail or start a reply: off without an active person (read-only), like the toolbar. */
export const ACTION_SHORTCUTS: ReadonlySet<MailShortcut> = new Set([
  'delete',
  'purge',
  'unread',
  'junk',
  'reply',
  'replyAll',
  'forward',
]);

export function isEditable(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  const tag = el.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable) return true;
  return el.closest('[contenteditable=""], [contenteditable="true"]') !== null;
}

/** An open modal (Dialog, command palette, menus rendered as dialogs) takes the keyboard. */
export function modalOpen(doc: Document = document): boolean {
  return doc.querySelector('[aria-modal="true"]') !== null;
}

/** Single-key shortcuts (the `G I` sequence is handled by the listener). */
export function matchShortcut(e: KeyLike): ShortcutId | null {
  if (e.altKey || e.metaKey) return null;
  if (e.ctrlKey) {
    if (!e.shiftKey && e.key.toLowerCase() === 'a') return 'selectAll';
    return null;
  }
  switch (e.key) {
    case '?':
      return 'help';
    case '/':
      return e.shiftKey ? 'help' : 'search';
    case 'ArrowUp':
      return e.shiftKey ? null : 'up';
    case 'ArrowDown':
      return e.shiftKey ? null : 'down';
    case 'Enter':
      return e.shiftKey ? null : 'open';
    case 'Delete':
      return e.shiftKey ? 'purge' : 'delete';
    case '!':
      return 'junk';
    case 'R':
      return e.shiftKey ? 'replyAll' : 'reply';
    default:
      break;
  }
  if (e.shiftKey) return null;
  switch (e.key) {
    case 'c':
      return 'compose';
    case 'u':
      return 'unread';
    case 'r':
      return 'reply';
    case 'f':
      return 'forward';
    default:
      return null;
  }
}

export type MailShortcutHandlers = Partial<Record<MailShortcut, () => void>> & { readOnly: boolean };

type Source = () => MailShortcutHandlers;
let current: Source | null = null;

/** The mail screen registers a getter of its current handlers; returns the unregister function. */
export function registerMailShortcuts(source: Source): () => void {
  current = source;
  return () => {
    if (current === source) current = null;
  };
}

/** Runs the registered handler. False when nothing handles the key (the browser default then stays). */
export function dispatchMailShortcut(id: MailShortcut): boolean {
  const handlers = current?.();
  if (!handlers) return false;
  if (handlers.readOnly && ACTION_SHORTCUTS.has(id)) return false;
  const run = handlers[id];
  if (!run) return false;
  run();
  return true;
}
