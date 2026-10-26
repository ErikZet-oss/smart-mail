// @vitest-environment node
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import { routeObjects } from './router';
import { ROUTES } from './routes';

/** SCREENS_SPEC §1 table: ID → list of routes (`W16a/b/c/d` expands to W16a, W16b, …). */
function specRoutes(): Map<string, string[]> {
  const spec = readFileSync(resolve(process.cwd(), '../docs/SCREENS_SPEC.md'), 'utf8');
  const section = spec.slice(spec.indexOf('## 1. Sitemap and routes'), spec.indexOf('## 2. Global shell'));
  const map = new Map<string, string[]>();
  for (const line of section.split('\n')) {
    const cells = line.split(/(?<!\\)\|/).map((c) => c.trim());
    const idCell = cells[1];
    const routeCell = cells[2];
    if (!idCell || !routeCell || !/^W\d/.test(idCell)) continue;
    const paths = [...routeCell.matchAll(/`([^`]+)`/g)].map((m) => m[1] ?? '');
    const [base, ...suffixes] = idCell.split('/');
    if (!base) continue;
    const prefix = base.replace(/[a-z]$/, '');
    const ids = [base, ...suffixes.map((s) => prefix + s)];
    ids.forEach((id, i) => map.set(id, ids.length > 1 ? (paths[i] ? [paths[i]] : []) : paths));
  }
  return map;
}

describe('route manifest (CLAUDE.md §10)', () => {
  const spec = specRoutes();

  it('parses the SCREENS_SPEC table', () => {
    expect(spec.get('W1')).toEqual(['/login']);
    expect(spec.get('W16b')).toEqual(['/404']);
  });

  it.each(Object.values(ROUTES))('$id has the route of SCREENS_SPEC §1', ({ id, path }) => {
    expect(spec.has(id), `${id} is not in SCREENS_SPEC §1`).toBe(true);
    expect(spec.get(id)).toContain(path);
  });

  it('every routed screen has a manifest entry', () => {
    const manifest = new Set<string>(Object.values(ROUTES).map((r) => r.id));
    for (const route of routeObjects) {
      if (route.path === '/' || route.path === '*') continue;
      expect(route.id && manifest.has(route.id), `route ${route.path} has no SCREENS_SPEC id`).toBe(true);
    }
  });
});
