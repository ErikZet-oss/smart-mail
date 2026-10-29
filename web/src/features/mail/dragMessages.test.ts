import { afterEach, describe, expect, it } from 'vitest';
import { canDropOn, droppedIds, endMessageDrag, MESSAGES_MIME, startMessageDrag } from './dragMessages';

/** jsdom has no DataTransfer — the subset the helpers use. */
function transfer(): DataTransfer {
  const data = new Map<string, string>();
  return {
    effectAllowed: 'none',
    dropEffect: 'none',
    get types() {
      return [...data.keys()];
    },
    setData: (type: string, value: string) => void data.set(type, value),
    getData: (type: string) => data.get(type) ?? '',
  } as unknown as DataTransfer;
}

describe('#96 drag & drop of messages', () => {
  afterEach(endMessageDrag);

  it('drop on another folder carries the ids', () => {
    const dt = transfer();
    startMessageDrag(dt, ['m1', 'm2'], 'inbox');
    expect(dt.effectAllowed).toBe('move');
    expect(canDropOn(dt, 'faktury')).toBe(true);
    expect(droppedIds(dt)).toEqual(['m1', 'm2']);
  });

  it('the folder the messages are in is no drop target', () => {
    const dt = transfer();
    startMessageDrag(dt, ['m1'], 'inbox');
    expect(canDropOn(dt, 'inbox')).toBe(false);
  });

  it('other drags (files, text) are ignored', () => {
    const dt = transfer();
    dt.setData('text/plain', 'hello');
    expect(canDropOn(dt, 'faktury')).toBe(false);
    dt.setData(MESSAGES_MIME, 'not json');
    expect(droppedIds(dt)).toEqual([]);
  });
});
