/** Roundcube-like date for MessageRow (UX_SPEC §2.8): Dnes HH:mm · Včera HH:mm · weekday · dd. mm. yyyy. */

const WEEKDAYS = ['Ne', 'Po', 'Ut', 'St', 'Št', 'Pi', 'So'] as const;

function atLocalMidnight(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

export function formatMailDate(iso: string | null | undefined, now = new Date()): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  const time = date.toLocaleTimeString('sk-SK', { hour: '2-digit', minute: '2-digit' });
  const dayDiff = Math.round((atLocalMidnight(now) - atLocalMidnight(date)) / 86_400_000);
  if (dayDiff === 0) return `Dnes ${time}`;
  if (dayDiff === 1) return `Včera ${time}`;
  if (dayDiff > 1 && dayDiff < 7) return `${WEEKDAYS[date.getDay()]} ${time}`;
  return date.toLocaleDateString('sk-SK', { day: 'numeric', month: 'numeric', year: 'numeric' });
}
