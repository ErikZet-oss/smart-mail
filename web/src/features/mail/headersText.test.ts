import { describe, expect, it } from 'vitest';

import { authSummary, headersText } from './headersText';

describe('W2p headers helpers', () => {
  it('all pass → one tick', () => {
    expect(authSummary({ spf: 'pass', dkim: 'pass', dmarc: 'pass' })).toBe('SPF, DKIM, DMARC ✓');
  });
  it('a failure is named', () => {
    expect(authSummary({ spf: 'pass', dkim: 'fail' })).toBe('SPF ✓, DKIM ✗');
  });
  it('nothing reported', () => {
    expect(authSummary(null)).toBeNull();
    expect(authSummary({ raw: 'x' })).toBeNull();
  });
  it('copy text keeps folding', () => {
    expect(
      headersText([
        { name: 'Received', value: 'from a\n  by b' },
        { name: 'To', value: 'x@smartmail.test' },
      ]),
    ).toBe('Received: from a\n  by b\nTo: x@smartmail.test');
  });
});
