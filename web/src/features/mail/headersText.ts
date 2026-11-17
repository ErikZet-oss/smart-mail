import type { MessageHeaders } from './mailApi';

const AUTH_KEYS = ['spf', 'dkim', 'dmarc'] as const;

/** „SPF, DKIM, DMARC ✓“ when all pass, otherwise each with ✓ / ✗; null when the server reported nothing. */
export function authSummary(auth: MessageHeaders['auth_results']): string | null {
  if (!auth) return null;
  const present = AUTH_KEYS.filter((k) => auth[k]);
  if (present.length === 0) return null;
  if (present.length === AUTH_KEYS.length && present.every((k) => auth[k] === 'pass')) {
    return 'SPF, DKIM, DMARC ✓';
  }
  return present.map((k) => `${k.toUpperCase()} ${auth[k] === 'pass' ? '✓' : '✗'}`).join(', ');
}

export function headersText(headers: MessageHeaders['headers']): string {
  return headers.map((h) => `${h.name}: ${h.value}`).join('\n');
}
