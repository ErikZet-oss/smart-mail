import { useSyncExternalStore } from 'react';

import type { ComposeDraft } from './composeApi';

export type SendWatch = {
  id: string;
  mailbox: string;
  generation: number;
  draft: ComposeDraft;
};

let watches: SendWatch[] = [];
let generation = 0;
const listeners = new Set<() => void>();
/** Toast keys that already fired, so a remount during the undo window does not stack duplicates. */
const announced = new Set<string>();

function emit(): void {
  for (const listener of listeners) listener();
}

export function watchSend(draft: ComposeDraft, mailbox: string): void {
  generation += 1;
  const next: SendWatch = { id: draft.id, mailbox, generation, draft };
  watches = [...watches.filter((item) => item.id !== draft.id), next];
  emit();
}

export function replaceWatchDraft(id: string, gen: number, draft: ComposeDraft): void {
  watches = watches.map((item) => (item.id === id && item.generation === gen ? { ...item, draft } : item));
  emit();
}

export function dropWatch(id: string, gen: number): void {
  watches = watches.filter((item) => !(item.id === id && item.generation === gen));
  emit();
}

export function getWatches(): readonly SendWatch[] {
  return watches;
}

/** Returns true the first time `key` is announced. */
export function markAnnounced(key: string): boolean {
  if (announced.has(key)) return false;
  announced.add(key);
  return true;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useSendWatches(): readonly SendWatch[] {
  return useSyncExternalStore(subscribe, getWatches, getWatches);
}

export function watchKey(items: readonly SendWatch[]): string {
  return items.map((item) => `${item.id}:${item.generation}`).join(',');
}
