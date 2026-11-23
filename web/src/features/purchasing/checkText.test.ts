import i18n from 'i18next';
import { describe, expect, it } from 'vitest';

import sk from '../../i18n/sk.json';
import { checkText, ruleKey } from './checkText';

await i18n.init({ lng: 'sk', resources: { sk: { translation: sk } }, interpolation: { escapeValue: false } });
const t = i18n.t.bind(i18n);

describe('checkText (pilot 2026-11-23: DL-B1 / DL-B6 name the branch and what is missing)', () => {
  it('DL-B6 without a template', () => {
    const c = { id: 'DL-B6', level: 'blocking' as const, params: { missing: ['template'] } };
    expect(ruleKey(c)).toBe('DL-B6_none');
    expect(checkText(t, c, 'Nitra')).toContain('Pobočka Nitra nemá vzorový dodací list');
  });
  it('DL-B6 incomplete template lists the missing values', () => {
    const c = { id: 'DL-B6', level: 'blocking' as const, params: { missing: ['Group_ID', 'Predkontace_ID'] } };
    expect(checkText(t, c, 'Nitra')).toContain('chýba: skupina zoznamu (DLP …), predkontácia');
  });
  it('DL-B6 VAT rate and DL-B1 branch settings', () => {
    expect(
      checkText(t, { id: 'DL-B6', level: 'blocking', params: { reason: 'vat_rate', rates: ['10', '5'] } }, 'Senica'),
    ).toContain('sadzbou DPH 10 %, 5 %');
    expect(checkText(t, { id: 'DL-B1', level: 'blocking', params: { missing: ['warehouse'] } }, 'Senica')).toContain(
      'Pobočke Senica chýba v Nastaveniach › Pobočky a osoby › Money: sklad pobočky.',
    );
    expect(checkText(t, { id: 'DL-B1', level: 'blocking', params: { missing: ['branch'] } }, null)).toContain(
      'Dodací list nemá priradenú pobočku',
    );
  });
});
