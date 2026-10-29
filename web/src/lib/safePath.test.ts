import { describe, expect, it } from 'vitest';
import { safeInternalPath } from './safePath';

describe('#85 safeInternalPath', () => {
  it.each(['/', '/mail/default/inbox', '/mail/default/inbox/t-1?x=1#a', '/settings/users'])('keeps %s', (p) => {
    expect(safeInternalPath(p)).toBe(p);
  });

  it.each([
    '//evil.test',
    '/\\evil.test',
    '/\\\\evil.test',
    '/mail\\..\\x',
    'https://evil.test',
    'javascript:alert(1)',
    'mail/inbox',
    '',
    '/\tevil',
    null,
    undefined,
    42,
  ])('rejects %s', (p) => {
    expect(safeInternalPath(p, '/fallback')).toBe('/fallback');
  });
});
