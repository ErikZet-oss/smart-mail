import { describe, expect, it } from 'vitest';

import sk from './sk.json';

function leaves(obj: unknown, prefix = ''): [string, unknown][] {
  if (obj && typeof obj === 'object') {
    return Object.entries(obj).flatMap(([k, v]) => leaves(v, prefix ? `${prefix}.${k}` : k));
  }
  return [[prefix, obj]];
}

describe('sk.json', () => {
  it('has only non-empty strings', () => {
    for (const [key, value] of leaves(sk)) {
      expect(typeof value, key).toBe('string');
      expect((value as string).trim(), key).not.toBe('');
    }
  });
});
