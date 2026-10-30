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

/** Re-auth for ⚠ admin changes (#54): the dialog asks for the mailbox password; true = re-authenticated, retry. */
type ReauthHandler = () => Promise<boolean>;
let reauthHandler: ReauthHandler | undefined;
export function onReauthRequired(handler: ReauthHandler | undefined): void {
  reauthHandler = handler;
}

function needsReauth(error: ApiError): boolean {
  return error.status === 401 && error.detail.code === 'reauth_required';
}

export type RequestOptions = {
  /** false = the caller shows the error inline (login screens); maintenance is always global. */
  global?: boolean;
  /** true = an unexpected server error (500 `server_error`) is shown inline by the caller, e.g. the reading pane
   * (#41); sign-in, maintenance and permission errors stay global. */
  inlineServerErrors?: boolean;
  /** internal: the request already went through the re-auth dialog once */
  retried?: boolean;
};

function isGlobal(error: ApiError, options: RequestOptions): boolean {
  if (error.status === 503 && error.detail.code === 'maintenance') return true;
  if (options.global === false) return false;
  return !(options.inlineServerErrors && error.status >= 500);
}

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
  if (response.ok) {
    if (response.status === 204) return undefined as T;
    const text = await response.text();
    if (!text) return undefined as T;
    return JSON.parse(text) as T;
  }

  const error = await toError(response);
  if (needsReauth(error)) {
    // never a logout: ask for the password once and repeat the same request
    if (reauthHandler && !options.retried && (await reauthHandler())) {
      return api<T>(method, path, body, { ...options, retried: true });
    }
    throw error;
  }
  if (globalHandler && isGlobal(error, options)) globalHandler(error);
  throw error;
}

/** Multipart upload. Does not set Content-Type — the browser adds the boundary. */
export async function apiForm<T>(
  method: string,
  path: string,
  body: FormData,
  options: RequestOptions = {},
): Promise<T> {
  const send = async (csrf: string | undefined): Promise<Response> =>
    fetch(path, {
      method,
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        ...(csrf ? { 'X-CSRF-Token': csrf } : {}),
      },
      body,
    });

  let response = await send(await ensureCsrf());
  if (response.status === 403) {
    const error = await toError(response.clone());
    if (error.detail.code === 'csrf') response = await send(await ensureCsrf(true));
  }
  if (response.ok) {
    const text = await response.text();
    return (text ? JSON.parse(text) : undefined) as T;
  }
  const error = await toError(response);
  if (needsReauth(error)) {
    if (reauthHandler && !options.retried && (await reauthHandler())) {
      return apiForm<T>(method, path, body, { ...options, retried: true });
    }
    throw error;
  }
  const isMaintenance = error.status === 503 && error.detail.code === 'maintenance';
  if (globalHandler && (isMaintenance || options.global !== false)) globalHandler(error);
  throw error;
}

/** "7F3A21C9" → "7F3A-21C9" (W16c). */
export function formatRef(ref: string): string {
  const clean = ref.replace(/[^0-9A-Za-z]/g, '').toUpperCase();
  return clean.length === 8 ? `${clean.slice(0, 4)}-${clean.slice(4)}` : clean;
}

/** JSON request whose answer is a file (e.g. a PDF preview, #139) — same CSRF, error and re-auth handling as `api`. */
export async function apiBlob(
  method: string,
  path: string,
  body?: unknown,
  options: RequestOptions = {},
): Promise<Blob> {
  const send = async (csrf: string | undefined): Promise<Response> =>
    fetch(path, {
      method,
      credentials: 'same-origin',
      headers: {
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
  if (response.ok) return response.blob();
  const error = await toError(response);
  if (needsReauth(error) && reauthHandler && !options.retried && (await reauthHandler())) {
    return apiBlob(method, path, body, { ...options, retried: true });
  }
  if (globalHandler && isGlobal(error, options)) globalHandler(error);
  throw error;
}
