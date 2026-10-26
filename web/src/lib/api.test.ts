import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { routeForError } from '../app/router';
import { clearCookies, mockApi } from '../test/mockApi';
import { api, ApiError, formatRef } from './api';

beforeEach(() => clearCookies());
afterEach(() => vi.unstubAllGlobals());

describe('api client', () => {
  it('fetches a CSRF token before the first unsafe request and sends it as a header', async () => {
    const { calls } = mockApi({ 'POST /api/auth/logout': { body: { ok: true } } });
    await api('POST', '/api/auth/logout');
    expect(calls.map((c) => c.key)).toEqual(['GET /api/auth/csrf', 'POST /api/auth/logout']);
    expect(calls[1]?.headers['X-CSRF-Token']).toBe('test-csrf');
  });

  it('retries once with a fresh token after a CSRF rejection', async () => {
    document.cookie = 'sm_csrf=stale';
    let first = true;
    const { calls } = mockApi({
      'POST /api/auth/logout': () => {
        if (first) {
          first = false;
          return { status: 403, body: { detail: { code: 'csrf' } } };
        }
        return { body: { ok: true } };
      },
    });
    await expect(api('POST', '/api/auth/logout')).resolves.toEqual({ ok: true });
    expect(calls.map((c) => c.key)).toEqual(['POST /api/auth/logout', 'GET /api/auth/csrf', 'POST /api/auth/logout']);
  });

  it('throws ApiError with the server detail', async () => {
    mockApi({ 'GET /api/auth/me': { status: 401, body: { detail: { code: 'unauthenticated', reason: 'expired' } } } });
    const error = await api('GET', '/api/auth/me').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).detail.reason).toBe('expired');
  });

  it('formats the W16c reference like 7F3A-21C9', () => {
    expect(formatRef('7f3a21c9')).toBe('7F3A-21C9');
  });
});

describe('routeForError', () => {
  const err = (status: number, detail: Record<string, unknown>) =>
    new ApiError(status, { code: 'x', ...detail } as { code: string });

  it.each([
    [err(401, { code: 'unauthenticated', reason: 'password_changed' }), '/login?reason=password-changed'],
    [err(401, { code: 'unauthenticated', reason: 'expired' }), '/login?reason=expired'],
    [err(401, { code: 'unauthenticated', reason: 'missing' }), '/login'],
    [err(503, { code: 'maintenance' }), '/maintenance'],
    [err(403, { code: 'forbidden' }), '/403'],
    [err(500, { code: 'server_error', ref: 'ABCD1234' }), '/500?ref=ABCD1234'],
  ])('%#', (error, target) => {
    expect(routeForError(error, '/mail/default/inbox')).toBe(target);
  });

  it('ignores a CSRF 403 and errors a screen shows itself', () => {
    expect(routeForError(err(403, { code: 'csrf' }), '/mail')).toBeNull();
    expect(routeForError(err(409, { code: 'conflict' }), '/mail')).toBeNull();
  });

  it('W1b: a deactivated active person (409) or an action without a person (403) opens the picker', () => {
    expect(routeForError(err(409, { code: 'person_inactive' }), '/mail/default/inbox')).toBe('/who');
    expect(routeForError(err(403, { code: 'person_required' }), '/mail/default/inbox')).toBe('/who');
    expect(routeForError(err(403, { code: 'read_only' }), '/mail/default/inbox')).toBe('/403');
  });
});
