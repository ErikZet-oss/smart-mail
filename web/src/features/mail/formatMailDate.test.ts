import { describe, expect, it } from 'vitest';

import { formatMailDate } from './formatMailDate';

describe('formatMailDate (MessageRow)', () => {
  // Local times, not a fixed offset: „Dnes / Včera“ are calendar days in the viewer's time zone, so a +01:00 literal
  // turned into another day in UTC+14 (#121 — the suite must pass in any TZ the runner happens to have).
  const local = (d: number, h: number, m = 0) => new Date(2026, 9, d, h, m).toISOString();
  const now = new Date(2026, 9, 26, 12, 0);

  it('formats today and yesterday like Roundcube', () => {
    expect(formatMailDate(local(26, 9, 42), now)).toMatch(/^Dnes /);
    expect(formatMailDate(local(25, 14, 10), now)).toMatch(/^Včera /);
  });

  it('uses weekday within 7 days and absolute date after', () => {
    expect(formatMailDate(local(24, 17, 15), now)).toMatch(/^\S{2} /);
    expect(formatMailDate(local(1, 10), now)).toMatch(/2026/);
  });

  it('returns empty for missing or invalid', () => {
    expect(formatMailDate(null)).toBe('');
    expect(formatMailDate('not-a-date')).toBe('');
  });
});
