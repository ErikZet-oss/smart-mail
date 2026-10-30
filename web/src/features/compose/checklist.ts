import type { ComposeCheck } from './composeApi';

export type ChecklistRow = {
  key: string;
  level: 'ok' | 'warning' | 'blocking';
  text: { ns: 'issue' | 'ok'; code: string; message?: string };
};

// SCREENS_SPEC W4a „Kontrola pred odoslaním“: the four checks that are always listed (green when they pass).
const LISTED = ['placeholder', 'multiple_companies', 'attachment_mentioned', 'language_mismatch'] as const;

/** Live checklist from the draft's server checks (re-computed on every autosave): problems first, then the passes. */
export function checklistRows(checks: readonly ComposeCheck[]): ChecklistRow[] {
  const issues: ChecklistRow[] = checks.map((c) => ({
    key: c.code,
    level: c.blocking ? 'blocking' : 'warning',
    text: { ns: 'issue', code: c.code, message: c.message },
  }));
  issues.sort((a, b) => Number(b.level === 'blocking') - Number(a.level === 'blocking'));
  const present = new Set(checks.map((c) => c.code));
  const passed: ChecklistRow[] = LISTED.filter((code) => !present.has(code)).map((code) => ({
    key: `${code}-ok`,
    level: 'ok',
    text: { ns: 'ok', code },
  }));
  return [...issues, ...passed];
}
