import { describe, expect, it } from 'vitest';

import { inlinePreviewUrl } from './composeExtensions';

describe('inline image preview (pilot: a pasted screenshot showed as a broken image)', () => {
  it('maps cid: to the draft preview URL and leaves other sources alone', () => {
    expect(inlinePreviewUrl('cid:snimka-1@smartmail', 'd-1')).toBe('/api/mail/compose/d-1/inline/snimka-1%40smartmail');
    expect(inlinePreviewUrl('https://www.example.com/a.png', 'd-1')).toBe('https://www.example.com/a.png');
    expect(inlinePreviewUrl('cid:x@y', null)).toBe('cid:x@y');
  });
});
