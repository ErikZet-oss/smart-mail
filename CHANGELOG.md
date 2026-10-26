# Changelog

All notable changes. Format: Keep a Changelog; versions follow the build phases (CLAUDE.md §12).

## [Unreleased] — Phase 1d: list & reading
### Added
- Threads, lazy message bodies, attachments and `user_settings` (migration `0006`); local file storage via
  `STORAGE_PATH` (ADR-006). HTML sanitized with `nh3`; remote images rewritten to a placeholder.
- Message API: list (Zoznam / Konverzácie), detail with body fetch, flags, bulk (incl. Vybavené), snooze, assign,
  source (.eml), attachment download, prefs (list + UI theme/classic).
- Web W2 list (`MessageRow`, filters, pagination, Výber / Konverzácie / Možnosti W2o), reading pane W2c (Roundcube
  toolbar; Reply/Forward disabled until 1e), bulk bar W2e, print W2m, source W2n, dark mode and Klasické zobrazenie.
- Tests: sanitize, threading, parse, message list/prefs/snooze; vitest for rows + date format. Real-server suite
  still skipped without `REAL_IMAP_TEST_*`.

## Phase 1c: shell & folders
### Added
- Compose service `imap-test` (Dovecot: IMAP + SPECIAL-USE, IDLE, CONDSTORE, QUOTA, ManageSieve) with fictional
  mailboxes `pilot@` / `plna@` (≥ 90 % quota) / `senica@smartmail.test` and seed tool `make imap-seed` (Roundcube
  folder set of D21). ADR-005.
- Data model (migration `0005`): `mailboxes`, `mailbox_access`, `folders_meta`, `messages` (envelopes); branch
  `mailbox_id` FK. Login provisions the own mailbox from `IMAP_LOGIN_*` and links it to the branch.
- IMAP sync: host guard (localhost / imap-test only outside prod unless `MAIL_SYNC_ALLOW_REAL_SERVER`), Redis lock,
  envelope fetch in batches, CONDSTORE flag updates, IDLE watcher on INBOX + 2-min poll of other subscribed folders
  (ARQ worker). Auth failure clears the stored password and revokes sessions (`password_changed`).
- Folder API: list / refresh / create / rename / delete / mark-read / empty / compact with ActivePerson, SK order of
  special folders + Slovak sort of own folders, quota `{percent, level}` (danger ≥ 90 %).
- Web: G1 rail (white logo, E-mail badge = inbox unread, disabled items of later phases, Odhlásiť), G3 folder column
  (⋮ mailbox menu, context menu, confirm/form dialogs, quota + Money ● grey), G4 toast stack, G5 dialogs, G6 banners
  (offline, IMAP error), G7 drop zone; W2 shell with Obnoviť and "Vyberte správu"; W12 Môj profil read-only
  placeholder. PersonChip always opens a menu with Môj profil + Odhlásiť (also with one person); below 820 px height
  Tmavý režim and O systéme move into it.
- Tests: 50 backend unit + IMAP integration against Dovecot (`REQUIRE_IMAP=1` in CI), real-server suite skipped until
  `REAL_IMAP_TEST_*` are set; 24 vitest + Playwright desktop/mobile screenshots next to Figma.

## Phase 1b: branches & "Kto ste?"
### Added
- `GET /api/auth/persons` and `POST /api/auth/person`: person picker of a branch mailbox (managers first, then Slovak
  alphabetical, covering persons included, inactive hidden), one click selects or switches — no PIN (D9) — audited
  as `auth.person_selected` / `auth.person_switched`. ADR-004.
- Device memory `device_person_memory` (migration `0004`): the last person on this device is preselected on the next
  login; M0 "Zapamätať na tomto telefóne" off forgets it.
- `409 person_inactive` when the active person was deactivated or removed from the branch (the web opens W1b);
  `ActivePerson` dependency (`403 person_required` / `403 read_only`) for actions from 1c on.
- Every audit entry of a signed-in request carries `account_id` and `person_id` (request-scoped audit actor).
- Web: W1b Kto ste? (desktop) and M0 (mobile) per Figma, "Pokračovať ako …" with Enter, "Prihlásiť sa iným e-mailom";
  W2b PersonChip with the "Kto pracuje?" popover, `Ctrl+Shift+P` and the 2 s toast "Teraz pracuje: … · podpis
  zmenený"; idle re-ask by the branch setting; components `Avatar` (colour = stable hash of the person id), `Switch`,
  `Toast`; shadow tokens in Tailwind. UX_SPEC W1b tile size 132 × 140 (Figma, D24).
- Tests: 24 backend tests `test_persons_1b.py` (W1b/W2b/M0/§9 ids), vitest for W1b, M0 and W2b, Playwright Flow 0
  (W1 → W1b → W2) and PersonChip switching on desktop + mobile, screenshots next to the Figma frames.

## Phase 1a: foundation & login
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
- Customer decisions D25–D27 (DECISIONS v2.11): accounts auto-created as viewer on the first login from
  `INTERNAL_DOMAINS`, first admins from `ADMIN_EMAILS`; per-IP limit 30 / 5 min with `LOGIN_IP_ALLOWLIST` for company
  IPs; mailbox password stored Fernet-encrypted (migration `0003`) and overwritten on change; W16a "Požiadať správcu"
  mails `ADMIN_CONTACT_EMAIL` (`GET /api/system/info`).
### Changed
- M-W1 follows its Figma frame (inline field icons, checkbox above the button, no eye toggle, no footer on phones);
  login logo 180 px in UX_SPEC/SCREENS_SPEC; 2FA lock-out text added to UX_SPEC §7.
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
