// Route manifest (CLAUDE.md §10): every route carries the screen ID of SCREENS_SPEC §1, the route-manifest test
// fails when a route has no ID there or the path differs. W12 = Settings sections (Phase 1f).

export type RouteEntry = { id: string; path: string; signedIn?: boolean };

export const ROUTES = {
  W1: { id: 'W1', path: '/login' },
  W1a: { id: 'W1a', path: '/login/2fa' },
  W1b: { id: 'W1b', path: '/who', signedIn: true },
  W2: { id: 'W2', path: '/mail/:mailbox/:folder', signedIn: true },
  W2c: { id: 'W2c', path: '/mail/:mailbox/:folder/:threadId', signedIn: true },
  W2m: { id: 'W2m', path: '/mail/:mailbox/:folder/:threadId/print', signedIn: true },
  W2n: { id: 'W2n', path: '/mail/:mailbox/:folder/:threadId/source/:messageId', signedIn: true },
  W4: { id: 'W4', path: '/compose', signedIn: true },
  W4draft: { id: 'W4', path: '/compose/:draftId', signedIn: true },
  W12: { id: 'W12', path: '/settings/:section/:sub?', signedIn: true },
  W16a: { id: 'W16a', path: '/403' },
  W16b: { id: 'W16b', path: '/404' },
  W16c: { id: 'W16c', path: '/500' },
  W17: { id: 'W17', path: '/maintenance' },
} as const satisfies Record<string, RouteEntry>;

/** Default landing route after sign-in (W2 Doručená pošta of the default mailbox). */
export const HOME = '/mail/default/inbox';
