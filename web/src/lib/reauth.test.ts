import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { routeForError } from '../app/router';
import { clearCookies, mockApi } from '../test/mockApi';
import { api, ApiError, onGlobalError, onReauthRequired } from './api';

beforeEach(() => clearCookies());
afterEach(() => {
  vi.unstubAllGlobals();
  onReauthRequired(undefined);
  onGlobalError(undefined);
});

const REAUTH = { status: 401, body: { detail: { code: 'reauth_required' } } };

describe('#54 re-auth for ⚠ admin changes', () => {
  it('asks for the password once and repeats the request', async () => {
    let first = true;
    const { calls } = mockApi({
      'PATCH /api/settings/admin/users/a1': () => {
        if (first) {
          first = false;
          return REAUTH;
        }
        return { body: { id: 'a1' } };
      },
    });
    const handler = vi.fn(async () => true);
    onReauthRequired(handler);
    await expect(api('PATCH', '/api/settings/admin/users/a1', { role: 'sales' })).resolves.toEqual({ id: 'a1' });
    expect(handler).toHaveBeenCalledTimes(1);
    expect(calls.filter((c) => c.key.startsWith('PATCH')).length).toBe(2);
  });

  it('a cancelled prompt throws without the global (logout) handler', async () => {
    mockApi({ 'PATCH /api/settings/admin/users/a1': REAUTH });
    const global = vi.fn();
    onGlobalError(global);
    onReauthRequired(async () => false);
    const error = await api('PATCH', '/api/settings/admin/users/a1', {}).catch((e: unknown) => e);
    expect((error as ApiError).detail.code).toBe('reauth_required');
    expect(global).not.toHaveBeenCalled();
  });

  it('never routes reauth_required to the login screen', () => {
    const error = new ApiError(401, { code: 'reauth_required' });
    expect(routeForError(error, '/settings/users')).toBeNull();
  });
});
