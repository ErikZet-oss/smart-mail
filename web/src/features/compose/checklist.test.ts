import { describe, expect, it } from 'vitest';
import { checklistRows } from './checklist';

describe('2d Kontrola pred odoslaním', () => {
  it('a clean draft lists the four passes', () => {
    expect(checklistRows([]).map((r) => [r.key, r.level])).toEqual([
      ['placeholder-ok', 'ok'],
      ['multiple_companies-ok', 'ok'],
      ['attachment_mentioned-ok', 'ok'],
      ['language_mismatch-ok', 'ok'],
    ]);
  });

  it('blocking first, then warnings, then what passed', () => {
    const rows = checklistRows([
      { code: 'external_recipient', blocking: false, message: 'external' },
      { code: 'placeholder', blocking: true, message: 'placeholder' },
    ]);
    expect(rows.map((r) => r.key)).toEqual([
      'placeholder',
      'external_recipient',
      'multiple_companies-ok',
      'attachment_mentioned-ok',
      'language_mismatch-ok',
    ]);
    expect(rows[0]?.level).toBe('blocking');
  });
});
