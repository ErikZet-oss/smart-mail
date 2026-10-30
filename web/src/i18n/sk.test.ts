import { describe, expect, it } from 'vitest';

import sk from './sk.json';
import skText from './sk.json?raw';

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

  it('has no duplicate key inside one object (JSON.parse silently keeps the last one)', () => {
    // pilot 2026-10-30: settings.branches.signature existed twice, so the hand-signature field showed
    // „Šablóna podpisu pobočky“ and Erik uploaded the signature in the wrong place
    const text = skText;
    const stack: Set<string>[] = [];
    const dups: string[] = [];
    // every string is consumed whole, so „{{name}}“ inside a value never counts as an object brace
    const token = /"((?:[^"\\]|\\.)*)"(\s*:)?|[{}]/g;
    for (const m of text.matchAll(token)) {
      if (m[0] === '{') stack.push(new Set());
      else if (m[0] === '}') stack.pop();
      else if (m[2] !== undefined) {
        const key = m[1] ?? '';
        const keys = stack[stack.length - 1];
        if (keys?.has(key)) dups.push(key);
        keys?.add(key);
      }
    }
    expect(dups).toEqual([]);
  });
});
