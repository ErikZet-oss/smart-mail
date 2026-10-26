import { vi } from 'vitest';

type Reply = { status?: number; body: unknown };
type Handler = (body: unknown) => Reply;

/** Minimal fetch mock keyed by "METHOD /path". Records calls; GET /api/auth/csrf sets the CSRF cookie. */
export function mockApi(handlers: Record<string, Handler | Reply>) {
  const calls: { key: string; body: unknown; headers: Record<string, string> }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost');
    const key = `${(init?.method ?? 'GET').toUpperCase()} ${url.pathname}`;
    const body = init?.body ? (JSON.parse(String(init.body)) as unknown) : undefined;
    calls.push({ key, body, headers: (init?.headers ?? {}) as Record<string, string> });
    if (key === 'GET /api/auth/csrf' && !(key in handlers)) {
      document.cookie = 'sm_csrf=test-csrf';
      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    }
    const handler = handlers[key];
    if (!handler) return new Response(JSON.stringify({ detail: { code: 'not_mocked' } }), { status: 404 });
    const reply = typeof handler === 'function' ? handler(body) : handler;
    return new Response(JSON.stringify(reply.body), {
      status: reply.status ?? 200,
      headers: { 'Content-Type': 'application/json' },
    });
  });
  vi.stubGlobal('fetch', fetchMock);
  return { calls, fetchMock };
}

export function clearCookies() {
  for (const part of document.cookie.split(';')) {
    const name = part.split('=')[0]?.trim();
    if (name) document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT`;
  }
}
