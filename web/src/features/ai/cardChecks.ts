import type { Suggestion } from './suggestionsApi';

export type CardCheck = { key: string; level: 'ok' | 'warning' | 'blocking'; params: Record<string, string> };
export type CardState = 'blocked' | 'attention' | 'lowconf' | 'ready';

export const LOW_CONFIDENCE = 0.6;

const LEVEL_ORDER = { blocking: 0, warning: 1, ok: 2 } as const;

/**
 * UX_SPEC §3.1 `CheckRow`s of a reply card: the guard results first (blocking, then warnings), then the green rows
 * for what passed („Príjemca = odosielateľ ✓ · Bez [[DOPLNIŤ]] ✓ …“).
 */
export function cardChecks(s: Suggestion): CardCheck[] {
  const ids = new Set(s.checks.map((c) => c.id));
  const rows: CardCheck[] = s.checks.map((c) => ({
    key: c.id,
    level: c.level,
    params: Object.fromEntries(
      Object.entries(c.params).map(([k, v]) => [k, Array.isArray(v) ? v.join(', ') : String(v)]),
    ),
  }));
  if (!ids.has('no_recipient') && !ids.has('new_recipient'))
    rows.push({ key: 'recipient_ok', level: 'ok', params: {} });
  if (!ids.has('placeholder')) rows.push({ key: 'placeholder_ok', level: 'ok', params: {} });
  if (!ids.has('unverified_number')) rows.push({ key: 'numbers_ok', level: 'ok', params: {} });
  return rows.sort((a, b) => LEVEL_ORDER[a.level] - LEVEL_ORDER[b.level]);
}

export function cardState(s: Suggestion): CardState {
  if (s.blocked || s.checks.some((c) => c.level === 'blocking')) return 'blocked';
  if (s.checks.some((c) => c.level === 'warning')) return 'attention';
  if ((s.confidence ?? 1) < LOW_CONFIDENCE) return 'lowconf';
  return 'ready';
}
