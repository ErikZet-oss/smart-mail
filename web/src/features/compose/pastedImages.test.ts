import { describe, expect, it } from 'vitest';

import { pastedImages } from './pastedImages';

function clipboard(entries: { kind: string; type: string; file?: File }[]): DataTransfer {
  return {
    items: entries.map((e) => ({ kind: e.kind, type: e.type, getAsFile: () => e.file ?? null })),
  } as unknown as DataTransfer;
}

describe('pastedImages (pilot: paste a Win+Shift+S screenshot into W4)', () => {
  it('returns a pasted screenshot with a readable name', () => {
    const shot = new File([new Uint8Array([137, 80, 78, 71])], 'image.png', { type: 'image/png' });
    const files = pastedImages(clipboard([{ kind: 'file', type: 'image/png', file: shot }]));
    expect(files).toHaveLength(1);
    expect(files[0]?.type).toBe('image/png');
    expect(files[0]?.name).toMatch(/^snimka-\d+\.png$/);
  });

  it('keeps a real file name and ignores text, HTML and unsupported types', () => {
    const photo = new File([new Uint8Array([1])], 'skrutka.jpg', { type: 'image/jpeg' });
    const files = pastedImages(
      clipboard([
        { kind: 'string', type: 'text/plain' },
        { kind: 'string', type: 'text/html' },
        { kind: 'file', type: 'image/webp', file: new File([], 'x.webp', { type: 'image/webp' }) },
        { kind: 'file', type: 'image/jpeg', file: photo },
      ]),
    );
    expect(files.map((f) => f.name)).toEqual(['skrutka.jpg']);
  });

  it('returns nothing for a text paste or no clipboard', () => {
    expect(pastedImages(clipboard([{ kind: 'string', type: 'text/plain' }]))).toEqual([]);
    expect(pastedImages(null)).toEqual([]);
  });
});
