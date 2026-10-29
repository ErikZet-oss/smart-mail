// react-router 6 stays for the pilot (ADR-013, #85): GHSA-wrjc-x8rr-h8h6 is an open redirect via a backslash in
// navigate targets. Every target that comes from router state or server data goes through this guard.

/** `value` if it is an internal app path (`/…`, not `//` or `/\`, no backslash or control characters), else `fallback`. */
export function safeInternalPath(value: unknown, fallback = '/'): string {
  if (typeof value !== 'string' || !value.startsWith('/')) return fallback;
  if (value.startsWith('//') || value.includes('\\') || hasControlChar(value)) return fallback;
  return value;
}

function hasControlChar(value: string): boolean {
  for (let i = 0; i < value.length; i += 1) {
    const code = value.charCodeAt(i);
    if (code < 0x20 || code === 0x7f) return true;
  }
  return false;
}
