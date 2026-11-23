import type { TFunction } from 'i18next';

import type { Check } from './purchasingApi';

/** Pilot 2026-11-23: DL-B1 / DL-B5 / DL-B6 said only „Pobočka nemá vzorový dodací list“. The text now names the branch
 * of the document and what exactly is missing (fields of the template, branch settings, VAT rates). */
export function ruleKey(c: Check): string {
  const missing = Array.isArray(c.params.missing) ? (c.params.missing as string[]) : [];
  if (c.params.reason) return `${c.id}_${String(c.params.reason)}`;
  if (c.id === 'DL-B1' && missing.includes('branch')) return 'DL-B1_nobranch';
  if (c.id === 'DL-B6') return missing.includes('template') ? 'DL-B6_none' : 'DL-B6_incomplete';
  return c.id;
}

export function checkText(t: TFunction, c: Check, branch: string | null): string {
  const missing = Array.isArray(c.params.missing) ? (c.params.missing as string[]) : [];
  const rates = Array.isArray(c.params.rates) ? (c.params.rates as string[]) : [];
  const params = {
    ...c.params,
    branch: branch ?? t('w6h.rules.noBranchName'),
    missing: missing.map((k) => t(`w6h.rules.fields.${k}`, { defaultValue: k })).join(', '),
    rates: rates.join(' %, '),
  };
  const key = ruleKey(c);
  return t(`w6h.rules.${key}`, { ...params, defaultValue: t(`w6h.rules.${c.id}`, { ...params, defaultValue: '' }) });
}
