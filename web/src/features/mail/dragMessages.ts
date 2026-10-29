// Drag & drop of message rows onto folders (#96, SCREENS_SPEC W2 „drag rows to G3 folder“).
// The ids travel in dataTransfer; the source folder is kept here because `dragover` cannot read dataTransfer data
// and a drop on the folder the messages are already in must not light up.

export const MESSAGES_MIME = 'application/x-smartmail-messages';

let current: { sourceFolderId: string | null } | null = null;

export function startMessageDrag(dt: DataTransfer, ids: readonly string[], sourceFolderId: string | null): void {
  dt.setData(MESSAGES_MIME, JSON.stringify(ids));
  dt.effectAllowed = 'move';
  current = { sourceFolderId };
}

export function endMessageDrag(): void {
  current = null;
}

/** True while message rows are dragged and `folderId` is a valid drop target for them. */
export function canDropOn(dt: DataTransfer, folderId: string): boolean {
  if (!Array.from(dt.types).includes(MESSAGES_MIME)) return false;
  return current?.sourceFolderId !== folderId;
}

export function droppedIds(dt: DataTransfer): string[] {
  try {
    const value: unknown = JSON.parse(dt.getData(MESSAGES_MIME) || '[]');
    return Array.isArray(value) ? value.filter((id): id is string => typeof id === 'string') : [];
  } catch {
    return [];
  }
}
