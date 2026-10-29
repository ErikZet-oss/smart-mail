import { describe, expect, it } from 'vitest';
import { cardChecks, cardState } from './cardChecks';
import type { Suggestion } from './suggestionsApi';

const base: Suggestion = {
  id: 's1',
  type: 'reply',
  status: 'pending',
  to: ['novak@abcstav.example'],
  subject: 'Re: Kópia faktúry',
  body: 'Dobrý deň',
  language: 'sk',
  rationale: null,
  confidence: 0.9,
  checks: [],
  blocked: false,
};

describe('#94 AiSuggestionCard checks and state', () => {
  it('a clean draft shows the three green rows and is ready', () => {
    expect(cardChecks(base).map((c) => [c.key, c.level])).toEqual([
      ['recipient_ok', 'ok'],
      ['placeholder_ok', 'ok'],
      ['numbers_ok', 'ok'],
    ]);
    expect(cardState(base)).toBe('ready');
  });

  it('blocking first, then warnings, then what passed; params become text', () => {
    const s: Suggestion = {
      ...base,
      blocked: true,
      checks: [
        { id: 'new_recipient', level: 'warning', params: { address: 'novak@abcstav.example' } },
        { id: 'unverified_number', level: 'blocking', params: { numbers: ['2026999', '30.10.2026'] } },
      ],
    };
    const rows = cardChecks(s);
    expect(rows.map((c) => c.key)).toEqual(['unverified_number', 'new_recipient', 'placeholder_ok']);
    expect(rows[0]?.params.numbers).toBe('2026999, 30.10.2026');
    expect(cardState(s)).toBe('blocked');
  });

  it('warnings make it attention; low confidence is grey', () => {
    expect(cardState({ ...base, checks: [{ id: 'language_mismatch', level: 'warning', params: {} }] })).toBe(
      'attention',
    );
    expect(cardState({ ...base, confidence: 0.4 })).toBe('lowconf');
  });
});
