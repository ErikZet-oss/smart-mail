import { describe, expect, it } from 'vitest';

import { formatMailDate } from './formatMailDate';

describe('formatMailDate (MessageRow)', () => {
  const now = new Date('2026-10-26T12:00:00+01:00');

  it('formats today and yesterday like Roundcube', () => {
    expect(formatMailDate('2026-10-26T09:42:00+01:00', now)).toMatch(/^Dnes /);
    expect(formatMailDate('2026-10-25T14:10:00+01:00', now)).toMatch(/^Včera /);
  });

  it('uses weekday within 7 days and absolute date after', () => {
    expect(formatMailDate('2026-10-24T17:15:00+01:00', now)).toMatch(/^\S{2} /);
    expect(formatMailDate('2026-10-01T10:00:00+01:00', now)).toMatch(/2026/);
  });

  it('returns empty for missing or invalid', () => {
    expect(formatMailDate(null)).toBe('');
    expect(formatMailDate('not-a-date')).toBe('');
  });
});
