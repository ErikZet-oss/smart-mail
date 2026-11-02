import { describe, expect, it } from 'vitest';

import { moneyNum } from './purchasingApi';

describe('moneyNum (Money formats, DOCUMENTS_SPEC §2.4)', () => {
  it('formats quantities, prices and totals like Money', () => {
    expect(moneyNum('5000', 4)).toBe('5\u00a0000,0000');
    expect(moneyNum('0.06125', 4)).toBe('0,0613');
    expect(moneyNum('668', 2)).toBe('668,00');
    expect(moneyNum('9.995', 2)).toBe('10,00');
    expect(moneyNum('-1234567.5', 2)).toBe('−1\u00a0234\u00a0567,50');
    expect(moneyNum(null, 2)).toBe('–');
    expect(moneyNum('abc', 2)).toBe('–');
  });
});

describe('addDec', () => {
  it('adds decimal strings exactly', async () => {
    const { addDec } = await import('./purchasingApi');
    expect(addDec('0.1', '0.2')).toBe('0.3');
    expect(addDec('306.00', '41')).toBe('347.00');
    expect(addDec('-1.50', '1.25')).toBe('-0.25');
  });
});
