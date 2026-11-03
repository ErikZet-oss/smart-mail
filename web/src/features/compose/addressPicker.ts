/** #203 W4g / M4b helpers: pure functions so the selection rules are unit-tested (vitest). */

export type PickTarget = 'to' | 'cc' | 'bcc';
export type PickEntry = { key: string; name: string; email: string; organization: string | null };
export type Fields = Record<PickTarget, string>;

/** Lower-cased e-mails already in a comma/semicolon separated field („Ján <jan@x.sk>, eva@y.sk“). */
export function emailsIn(raw: string): Set<string> {
  const out = new Set<string>();
  for (const part of raw.split(/[,;]+/)) {
    const m = part.match(/<([^>]+)>/);
    const email = (m ? m[1] : part)?.trim().toLowerCase();
    if (email && email.includes('@')) out.add(email);
  }
  return out;
}

function quoteName(name: string): string {
  // a comma or semicolon inside a name would split the address in parseAddrs → drop them, never the e-mail
  return name
    .replace(/[,;<>"]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

export function formatEntry(e: PickEntry): string {
  const name = quoteName(e.name);
  return name && name.toLowerCase() !== e.email.toLowerCase() ? `${name} <${e.email}>` : e.email;
}

/**
 * Adds the picked entries to one field. Addresses already in Komu, Kópia or Skrytá kópia are not added again
 * (issue #203), and the same address picked twice is added once. Returns the new fields and how many were added.
 */
export function addToField(fields: Fields, target: PickTarget, picked: PickEntry[]): { fields: Fields; added: number } {
  const present = new Set([...emailsIn(fields.to), ...emailsIn(fields.cc), ...emailsIn(fields.bcc)]);
  const parts: string[] = [];
  for (const e of picked) {
    const key = e.email.trim().toLowerCase();
    if (!key.includes('@') || present.has(key)) continue;
    present.add(key);
    parts.push(formatEntry(e));
  }
  if (!parts.length) return { fields, added: 0 };
  const current = fields[target].trim().replace(/[,;]\s*$/, '');
  return {
    fields: { ...fields, [target]: current ? `${current}, ${parts.join(', ')}` : parts.join(', ') },
    added: parts.length,
  };
}

/** „Vybrať všetkých v zozname“: checked / unchecked / mixed for the rows that are visible now. */
export function selectAllState(visible: PickEntry[], selected: ReadonlyMap<string, PickEntry>): boolean | 'mixed' {
  if (!visible.length) return false;
  const n = visible.filter((e) => selected.has(e.key)).length;
  return n === 0 ? false : n === visible.length ? true : 'mixed';
}

/** Toggles all visible rows; the selection in other address books and searches is kept. */
export function toggleAll(visible: PickEntry[], selected: ReadonlyMap<string, PickEntry>): Map<string, PickEntry> {
  const next = new Map(selected);
  if (selectAllState(visible, selected) === true) for (const e of visible) next.delete(e.key);
  else for (const e of visible) next.set(e.key, e);
  return next;
}

/** A contact with several e-mails → one row per e-mail (simplest; written in SCREENS_SPEC W4g). */
export function contactRows(c: {
  display_name: string;
  organization: string | null;
  emails: { email: string }[];
}): PickEntry[] {
  return c.emails
    .filter((e) => e.email && e.email.includes('@'))
    .map((e) => ({
      key: e.email.trim().toLowerCase(),
      name: c.display_name,
      email: e.email.trim(),
      organization: c.organization,
    }));
}

export function matches(e: PickEntry, q: string): boolean {
  const term = q.trim().toLowerCase();
  if (!term) return true;
  return [e.name, e.email, e.organization ?? ''].some((v) => v.toLowerCase().includes(term));
}
