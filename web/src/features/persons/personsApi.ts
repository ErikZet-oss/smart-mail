import { api } from '../../lib/api';
import type { Me, Person } from '../auth/authApi';

export type Picker = {
  branch: string | null;
  email: string;
  /** Manager first, then Slovak alphabetical (server order, PRODUCT_SPEC §2.0). */
  persons: Person[];
  current_person_id: string | null;
  /** Last person on this device, preselected with "Pokračovať ako …" (Enter). */
  last_person_id: string | null;
  /** Branch setting: after this many idle minutes the picker comes back (PRODUCT_SPEC §2.0). */
  idle_ask_minutes: number | null;
};

export const PICKER_KEY = ['persons'] as const;

export const fetchPicker = () => api<Picker>('GET', '/api/auth/persons');

export const choosePerson = (personId: string, rememberDevice: boolean) =>
  api<Me>('POST', '/api/auth/person', { person_id: personId, remember_device: rememberDevice }, { global: false });

/** "Jana Nováková" → "J" (W1b, W2b) or "JN" (M0), as in the Figma frames. */
export function initials(person: Pick<Person, 'first_name' | 'last_name'>, letters: 1 | 2): string {
  const first = person.first_name.trim().charAt(0);
  const last = person.last_name.trim().charAt(0);
  return (letters === 1 ? first || last : `${first}${last}`).toLocaleUpperCase('sk');
}
