import { describe, expect, it } from 'vitest';

import { sizeOf, withoutSize } from './newArticleText';

describe('D32 new article texts', () => {
  it('reads the thread size like the backend proposal', () => {
    expect(sizeOf('Skrutka DIN 933 M10x30 A2')).toBe(10);
    expect(sizeOf('mat. m8 A2')).toBe(8);
    expect(sizeOf('Podložka bez rozmeru')).toBeNull();
    expect(sizeOf('FXM10')).toBeNull();
  });
  it('drops the size from the main card name', () => {
    expect(withoutSize('Šroub ISO 7380 M6x16 A2 TX')).toBe('Šroub ISO 7380 A2 TX');
    expect(withoutSize('Tyč závitová 4.8 ZN 2m M10')).toBe('Tyč závitová 4.8 ZN 2m');
  });
});
