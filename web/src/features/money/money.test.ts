import { describe, expect, it } from 'vitest';

import { day, money } from './moneyApi';

describe('Money formatting (Decimal strings, never floats)', () => {
  it('formats amounts in Slovak style', () => {
    expect(money('1234.5')).toBe('1 234,50 €');
    expect(money('0.1')).toBe('0,10 €');
    expect(money('1000000')).toBe('1 000 000,00 €');
    expect(money('-12.345')).toBe('−12,34 €');
  });
  it('formats dates', () => {
    expect(day('2026-03-05')).toBe('5. 3. 2026');
    expect(day('2026-10-31T00:00:00')).toBe('31. 10. 2026');
    expect(day(null)).toBe('–');
  });
});
