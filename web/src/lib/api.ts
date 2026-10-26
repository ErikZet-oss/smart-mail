// Thin client for the Smart Mail API: cookies (server-side session), CSRF header, error shape
// `{"detail": {"code": ..., ...}}` (app/core/middleware.py).

export type ApiErrorDetail = { code: string; [key: string]: unknown };

export class ApiError extends Error {
  readonly status: number;
  readonly detail: ApiErrorDetail;

  constructor(status: number, detail: ApiErrorDetail) {
    super(`${status} ${detail.code}`);
    this.status = status;
    this.detail = detail;
  }
}

const CSRF_COOKIE = 'sm_csrf';
const SAFE = new Set(['GET', 'HEAD', 'OPTIONS']);

function readCookie(name: string): string | undefined {
  for (const part of document.cookie.split(';')) {
    const [key, ...rest] = part.trim().split('=');
    if (key === name) return decodeURIComponent(rest.join('='));
  }
  return undefined;
}

async function ensureCsrf(force = false): Promise<string> {
  const existing = readCookie(CSRF_COOKIE);
  if (existing && !force) return existing;
  await fetch('/api/auth/csrf', { credentials: 'same-origin' });
  return readCookie(CSRF_COOKIE) ?? '';
}

async function toError(response: Response): Promise<ApiError> {
  let detail: ApiErrorDetail = { code: 'http_error' };
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (body.detail && typeof body.detail === 'object' && 'code' in body.detail) {
      detail = body.detail as ApiErrorDetail;
    }
  } catch {
    // not JSON (proxy error page) – keep the generic code
  }
  return new ApiError(response.status, detail);
}

/** Global reaction to errors any screen can get (W1c, W17, W16c). Set by the router. */
type GlobalHandler = (error: ApiError) => void;
let globalHandler: GlobalHandler | undefined;
export function onGlobalError(handler: GlobalHandler | undefined): void {
  globalHandler = handler;
}

export type RequestOptions = {
  /** false = the caller shows the error inline (login screens); maintenance is always global. */
  global?: boolean;
};

export async function api<T>(method: string, path: string, body?: unknown, options: RequestOptions = {}): Promise<T> {
  const send = async (csrf: string | undefined): Promise<Response> =>
    fetch(path, {
      method,
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...(csrf ? { 'X-CSRF-Token': csrf } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });

  const unsafe = !SAFE.has(method.toUpperCase());
  let response = await send(unsafe ? await ensureCsrf() : undefined);
  if (unsafe && response.status === 403) {
    const error = await toError(response.clone());
    if (error.detail.code === 'csrf') response = await send(await ensureCsrf(true));
  }
  if (response.ok) return (await response.json()) as T;

  const error = await toError(response);
  const isMaintenance = error.status === 503 && error.detail.code === 'maintenance';
  if (globalHandler && (isMaintenance || options.global !== false)) globalHandler(error);
  throw error;
}

/** "7F3A21C9" → "7F3A-21C9" (W16c). */
export function formatRef(ref: string): string {
  const clean = ref.replace(/[^0-9A-Za-z]/g, '').toUpperCase();
  return clean.length === 8 ? `${clean.slice(0, 4)}-${clean.slice(4)}` : clean;
}
