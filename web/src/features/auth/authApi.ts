import { safeInternalPath } from '../../lib/safePath';
import { api } from '../../lib/api';

export type Person = {
  id: string;
  first_name: string;
  last_name: string;
  full_name: string;
  role: string;
  function: string | null;
  is_manager: boolean;
  photo_url?: string | null;
};

export type Me = {
  account_id: string;
  email: string;
  kind: 'personal' | 'branch';
  branch: string | null;
  person: Person | null;
  needs_person: boolean;
  read_only: boolean;
};

export type LoginResult = { next: '2fa' | '2fa-setup' | 'who' | 'app'; me: Me | null };

export const login = (email: string, password: string, remember: boolean) =>
  api<LoginResult>('POST', '/api/auth/login', { email, password, remember }, { global: false });

export const verifyMfa = (code: string, rememberDevice: boolean) =>
  api<LoginResult>('POST', '/api/auth/2fa', { code, remember_device: rememberDevice }, { global: false });

export const logout = () => api<{ ok: boolean }>('POST', '/api/auth/logout');

export const fetchMe = () => api<Me>('GET', '/api/auth/me');

/** Desktops recognised as shared branch PCs get "Zostať prihlásený" on by default (SCREENS_SPEC W1). */
export const SHARED_DEVICE_KEY = 'sm.sharedDevice';

export function rememberAfterLogin(me: Me | null): void {
  if (me?.kind === 'branch') localStorage.setItem(SHARED_DEVICE_KEY, '1');
}

/** Where to go after signing in: the route the user was on (W1c), or the inbox. */
export function returnTo(state: unknown): string {
  const from = (state as { from?: unknown } | null)?.from;
  const path = safeInternalPath(from);
  return path.startsWith('/login') ? '/' : path;
}
