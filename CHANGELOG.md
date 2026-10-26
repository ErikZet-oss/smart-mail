# Changelog

All notable changes. Format: Keep a Changelog; versions follow the build phases (CLAUDE.md §12).

## [Unreleased] — Phase 1a: foundation & login
### Added
- Data model (migration `0002`): `branches`, `persons`, `person_branches`, `accounts`, `sessions`, `audit_log`
  (append-only, enforced by a database trigger).
- Mailbox login via IMAP like Roundcube (`POST /api/auth/login`), server-side sessions (12 h idle, "Zostať
  prihlásený" 30 days or the branch limit), CSRF double-submit token, login rate limit per account and IP (5 wrong
  attempts → 5 min), logout everywhere on a detected mailbox password change, optional TOTP 2FA with backup codes and
  "Zapamätať zariadenie na 30 dní" (`POST /api/auth/2fa`), `GET /api/auth/me`, logout, maintenance mode
  (`/api/system/maintenance`), 500 responses with a reference code, security headers. ADR-003.
- CLI `python -m app.cli` (add-account, add-person, maintenance on/off) until the admin settings exist.
- Web: router with a route manifest checked against SCREENS_SPEC §1, API client (CSRF, global error routing), screens
  W1 Prihlásenie (+ mobile), W1c, W1a Overenie (2FA), W16a 403, W16b 404, W16c 500, W17 Údržba aligned to the Figma
  frames; a temporary signed-in page on `/who` and `/mail/...` until 1b/1c.
- Tests: TOTP RFC 6238 vectors, CSRF/cookie signing (Hypothesis), every login flow against PostgreSQL + Redis, IMAP
  login against a local stub server, vitest for the screens, Playwright e2e (desktop + mobile) with screenshots; CI
  runs PostgreSQL/Redis services and a Playwright job.
### Fixed
- Non-ASCII CSRF header crashed the comparison (500 instead of 403) — regression test added.

## [0.1.0] — 2026-10-26 — Phase 0: setup
### Added
- Specification package v2.10 (CLAUDE.md, docs/, DECISIONS D1–D24, FIGMA_MAP, design tokens, brand, Roundcube
  references, print templates, golden fixtures, Money schema, probe tools).
- Backend skeleton `app/`: settings for every variable of CLAUDE.md §13, structlog JSON logging, `/healthz`, `/readyz`
  (database + Redis), `/api/version`, ARQ worker with heartbeat cron, Alembic with migration `0001` (pgvector,
  unaccent, pgcrypto).
- Money bridge skeleton `bridge/`: mock backend, TEST agenda label, `/healthz`, `/readyz`, writes disabled in code.
- Web skeleton `web/`: React + Vite + TypeScript strict + Tailwind mapped to design tokens, Slovak i18n, phase-0 page
  with server status.
- Quality gates from day one: no `float(` in money code, tokens copy check, GraphQL schema drift check, fixtures
  marked fictional, golden print documents (< 0.5 % pixel diff).
- Docker Compose stack (Postgres/pgvector, Redis, S3 storage (SeaweedFS, ADR-002), ClamAV, Mailpit, bridge, app, worker, web) and GitHub Actions
  CI with a compose smoke test; `.env.example` documenting every variable; ADR-001; Figma MCP config `.mcp.json`.
### Fixed
- CLAUDE.md Phase 4 still referred to DL-W1–W7 → DL-W1–W8 (D23).
