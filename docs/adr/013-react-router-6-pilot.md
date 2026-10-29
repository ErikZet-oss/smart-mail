# ADR-013: Stay on react-router 6 for the pilot (issue #85)

- Status: accepted (Erik, option B on #85)
- Context: `npm audit` (#81) reports two moderate advisories for `react-router` / `react-router-dom` 6.x. Both are fixed only in 7.x, a major upgrade:
  - **GHSA-wrjc-x8rr-h8h6**: open redirect via a backslash in `<Link>` / `useNavigate` targets (a bypass of CVE-2025-68470);
  - **GHSA-337j-9hxr-rhxg**: constructor injection in `deserializeErrors()` during SSR hydration.

  There are also 4 low advisories (`deepmerge` via `vite-plugin-pwa` → `workbox-build`). They affect build time only. The CI gate is `npm audit --omit=dev --audit-level=high`.

## Decision
1. Keep react-router 6.x until Phase 7 (pilot hardening). Upgrade to 7.x there and run the full e2e suite.
2. GHSA-337j-9hxr-rhxg does not apply: Smart Mail is a client-rendered SPA with no SSR and no hydration.
3. GHSA-wrjc-x8rr-h8h6 is mitigated in our code:
   - Every navigation target that does not come from a constant or a route builder goes through `safeInternalPath` (`web/src/lib/safePath.ts`). It allows only paths that start with `/`, and rejects `//`, any backslash and control characters. Anything else falls back to an internal default.
   - Covered targets: the `from` state after login, W1a, W1b, W16, W17 (`returnTo`) and the `href` of a notification (server data).
   - There is no `?next=`-style query parameter.
   - Unit test: `web/src/lib/safePath.test.ts`.
4. A new navigation target taken from state, a URL or server data must use `safeInternalPath`. Code review checks this.

## Consequences
- `npm audit` keeps showing 2 moderate advisories until Phase 7. This is tracked in #85 (Phase 7).
- The upgrade to 7.x in Phase 7 is a dependency change and goes through the usual approval.
