# Changelog

All notable changes. Format: Keep a Changelog; versions follow the build phases (CLAUDE.md §12).

## [Unreleased] — Phase 2a: AI foundation (provider, schema, pipeline gates)

- **D31 / ADR-011**: Claude API (`LLM_PROVIDER=anthropic`); Bedrock interface stub only. ADR records official
  Anthropic data handling (processing location, retention, training, DPA) and cost per 1 000 mails for classify/draft.
  Model ids only from env — never `latest`.
- `LLMProvider` + `NullLLMProvider` (no key); `ai_runs` / `classifications` / `ai_suggestions` / `feature_flags`;
  `mailboxes.ai_enabled_at`; AI off by default until enabled (sets `ai_enabled_at`).
- Worker hook after sync gated by `ai_enabled_at`, D21 folders, Message-ID idempotency; AV gate helper; daily budget
  check; `ai_shadow_mode` flag seeded. **No classify UI / suggestion cards** (2b+).
- `deploy/install.sh` asks for `AI_DAILY_BUDGET_USD` (default 5) and Claude env; `tools/eval_label.py` + fictional
  `fixtures/ai/eval_smoke/` only (no real mail in git).

## [Unreleased] — Phase 1h-e (PR 5): Roundcube import, vacation EN/DE, W9/W10 empty, axe

- `tools/roundcube_import.py` — vCard + identities + Odpovede only (no filters); dry-run default; fixtures
  `@smartmail.test` only; optional read-only Roundcube DSN (SELECT).
- Vacation (Mimo kancelárie): **one** Sieve rule / one text — SK, then `---`, then EN, then DE (only filled
  languages). No `Accept-Language`, no `stop`. Subject via `variables`: `set "orig" "${1}"` +
  `:subject "Mimo kancelárie: ${orig}"` (omit `:subject` if the server lacks `variables`). Loading a legacy
  three-rule script merges into one. W12-06 help under EN/DE: „Odpoveď sa odošle v jednom e-maile…“.
  imap-test: LMTP + local sendmail stub; integration test checks ManageSieve script + real auto-reply.
- W9: viewer hides Upraviť / Zmazať / Import; empty / pick illustration per Figma.
- W10: empty tips + illustration + „Hľadať vo všetkých schránkach“.
- Playwright axe: no serious/critical on mail, contacts, search, settings.
- Deploy default mail host `mail.nameserver.sk` (IMAP 993/SSL, SMTP 465/SSL or 587/STARTTLS); `install.sh`
  probes 993/465/4190 with Slovak messages and **never fails** when 4190 is down.

## [Unreleased] — Phase 1h-d (PR 4): W4c schedule, W4f popup, ClamAV

- **W4c** Naplánovať odoslanie: send-menu presets (Zajtra 8:00 / Pondelok 8:00 / Vlastný čas), chip + cancel;
  worker cron flushes due scheduled drafts.
- **W4f** Okno písania: `?popup=1` 720×640 chrome, minimize bar, max 3 popups, „Otvoriť v novom okne“.
- **ClamAV**: `scan_bytes` on compose upload + inbound attachments; infected rejected (422); unreachable → skipped.
  Worker re-scans `skipped`/`error` every 15 min (batch 200). UI: „Ešte neskontrolované antivírusom“ + confirm
  before download. Phase-2 rule (AI_ASSISTANT): AI processes only `av_status=clean` attachments.
- **Downloads**: RFC 6266/5987 `Content-Disposition` (`filename` ASCII + `filename*=UTF-8''…`) so Slovak names
  (č/š/ž/ľ) no longer crash latin-1 headers.
- `web/tsconfig.tsbuildinfo` removed from git / gitignored.
- Deploy: `nginx-active.conf` (gitignored) generated from DEPLOY_MODE — never overwrite git templates;
  CI: edit `nginx-deploy.vps.conf` → update regenerates active conf.

## [Unreleased] — Phase 1h-f (PR 6): VPS deploy (Caddy / Cloudflare Tunnel)

- `deploy/install.sh` (vps | tunnel | CI), `update.sh` (rollback on failure), `status.sh`, `backup.sh` (7 days).
- Compose stack without Mailpit / imap-test; edge Caddy (Let’s Encrypt) or cloudflared; other ports on 127.0.0.1.
- `LOGIN_ALLOWLIST`, `FEATURE_MONEY=false` (Money UI hidden; mock bridge only). ADR-010.
- CI job runs `deploy/ci-smoke.sh` (no certificate, no tunnel). README „Nasadenie“ (SK).
- Real client IP: nginx `$proxy_add_x_forwarded_for` + Docker `real_ip`, proto from Caddy; tunnel-only
  `CF-Connecting-IP` (vps Caddy strips it); `FORWARDED_ALLOW_IPS` = Docker networks (never `*`).
  D26 tests: two IPs + audit IP; vps spoofed CF header ignored.
- Caddy HSTS `max-age=31536000` + security headers for `/api`; pinned `caddy:2.11.7-alpine`,
  `cloudflared:2026.10.4`. `update.sh`: backup before migrate, `git reset --hard` on branch
  (CI: local `ci-deploy` keeps PR checkout, not origin/main); restore hint on failure.
  `backup.sh` writes S3 tar as host user so CI chmod works. `install.sh`: ufw; keep `.env` silent.
- `/api/docs` + `/api/openapi.json` off outside `APP_ENV=dev`. Deploy CI smoke independent of backend job.

## [Unreleased] — Phase 1h-c: W13 tour, W14/M16, W15, W15b, classic

- **W13 / M-W13** Úvodná prehliadka (desktop Phase-1 steps + branch PersonChip step; mobile 3 steps).
- **W14 + M16** in-app notifications (sync failure, assignment/handover only — no Web Push / Money / AI).
  API returns `kind` + params (no SK strings); UI maps error codes (Nesprávne heslo / Server nedostupný…).
  Href → mailbox inbox or thread; ids include event time; dismiss list capped (500 / 30 days); self-assign skipped.
- **W15** Klávesové skratky (`?`) — Phase-1 groups only.
- **W15b** O systéme + **M18** row that opens it; restart tour; provider admin link (D20).
- **Klasické zobrazenie**: `data-classic` on `<html>`, list banner, filter chips remain hidden.

## [Unreleased] — Phase 1h-b: mobile M8 / M9 / M15 / M18

- **M8** Hľadanie: full-screen mobile search with recent queries; sender address opens compose (not mailto).
- **M9** Nastavenia: mobile section index (SETTINGS_SPEC §M9 Phase-1 subset); desktop-only group for
  folders/identity/filters/admin; AI and notifications omitted until later phases.
- **M15** Kontakty: list ↔ detail stack; e-mail opens Smart Mail compose (signature + audit); `tel:` kept for phones.
- **M18** Viac: Kontakty, Nastavenia, Prepnúť osobu, Vzhľad (Svetlý / Tmavý / Podľa zariadenia), Odhlásiť
  (no O systéme until 1h-c with W15b; no Dnes / Doklady).

## [Unreleased] — Phase 1h-a: PWA + mobile shell (M0–M4)

- Installable PWA (`vite-plugin-pwa`): manifest SK, icons from `design/brand/`, SW with `/api` NetworkOnly,
  `navigateFallbackDenylist` for `/api/`, `/healthz`, `/readyz` (OIDC / docs must not get `index.html`);
  apple-touch + theme-color.
- Mobile shell ≤639 px: bottom nav Phase-1 only (E-mail / Kontakty / Viac), interim Viac sheet, hide nav on
  M3/M4. M1 app bar + FAB „Vytvoriť“, M2 folder drawer, **left swipe Vybavené only** (Odložiť = Phase 5,
  not shown), long-press multi-select.
- M0 reuses W1b mobile layout; Playwright e2e `phase1h.spec.ts` against vite preview (SW registered).
- W14 + M16 stay together in 1h-c (Phase-1 kinds: sync fail, assignment/handover). M-W13 with W13 in 1h-c.
  Production deploy = plan-only PR 6 until go-ahead.

## [Unreleased] — Phase 1g: contacts & search (UI)

- Screens **W9** Kontakty, **W10** Hľadanie, **W11** Ctrl+K basic palette (no Firmy/Doklady/Asistent).
- W10 corpus banner „Hľadá sa v správach od …“; special-char query → 200; Celá správa finds `firma.sk` via address LIKE.
- First sync downloads **full** subscribed-folder history (`SEARCH ALL`) — documented in README.

## [Unreleased] — Phase 1g: contacts & search (backend)

- Local address books (Osobné / Zdieľané), groups, contacts CRUD; vCard 2.1/3.0 import/export (Roundcube + QP
  CHARSET fixtures); compose autocomplete. Contacts only in DB — IMAP never written. Viewer: shared book read-only
  (403). Shared mutations audited. Partial unique index for one shared book. Import limits 5 MB / 5 000 contacts (413).
- Mail search: Roundcube scope/fields; prefix FTS (`to_tsquery` + `:*` after unaccent); Od/Komu/Kópia also substring
  LIKE (escaped); weighted `search_vector` (A/B/D); `pg_trgm` GIN; subfolders `startswith(..., autoescape=True)`.
  Search covers **downloaded** messages only (README). Migration `0010`+`0011`; ADR-009.
- Money search → Phase 3; AI search → Phase 2.

## [Unreleased] — Phase 1f: settings + send guard

- Send guard (ADR-008): outside prod, SMTP only via Mailpit/localhost unless `MAIL_SEND_ALLOW_REAL_SERVER`;
  recipients limited to `@smartmail.test` + `MAIL_SEND_TEST_ALLOWLIST` (even with the flag).
- W4e: edit signature for this message only (`<>` source view, D22). W4c/W4f deferred to 1h.
- Settings W12: sections 01–06, 09, 09b, 10–12 — preferences, folders hint, identities + profile, Odpovede,
  Filtre + Mimo kancelárie (ManageSieve), security sessions, provider (D20), admin users / branches / mailboxes.
  Schema: `settings_schema.json` + `web/src/features/settings/schema.ts`. HTML signature editor (D22).
- Migration `0008` mailbox SMTP/Sieve/provider URL + person profile fields. Test against local `imap-test`;
  `REAL_IMAP_*` still skipped. ClamAV still deferred to 1h.
- Filtre / Mimo kancelárie: Roundcube `# rule:[Name]` parse via sievelib; load→save keeps conditions (Od →
  fileinto); unsupported rules stay raw („Pravidlo z Roundcube (len na čítanie)“); vacation writes into the
  **same active script** (never activates another set); Od–do + SK/EN/DE; script backup + „Obnoviť predchádzajúcu
  verziu“ (migration `0009`). Fixture `fixtures/sieve/roundcube_filters.sieve`.
- Filtre validation: ≥ 1 non-empty condition (422 SK message); size must be a positive integer; `compile_condition`
  never emits a match-all test. Telo = Sieve `body` extension; Hlavička = custom header name. Readonly rules take
  `raw` from the live script on save. PUT filters / vacation / restore require send access + non-viewer (admin
  always). W12-06 shows „Platí pre celú schránku“ + who last changed vacation (audit).
- **Known limitation (→ 1h):** EN/DE vacation bodies are stored in settings but **not** written to Sieve yet
  (RFC 5230 has one reason string). Phase 1h: reply by language via multiple vacation rules.

## [Unreleased] — Phase 1e: compose

- Compose W4: reply/forward/new, identities, branch signature with active person, Odpovede picker (W4d), attachments
  (S3), drafts autosave 30 s, undo send (`UNDO_SEND_SECONDS`), priority, delivery receipt, pre-send checks (W4b).
- Bodies fetched with **BODY.PEEK[] only** (never RFC822). Attachments/raw messages on **S3** (SeaweedFS in compose;
  `STORAGE_BACKEND=local` for unit tests only). ADR-007.
- IMAP seed ≥ 60 fictional messages (long subjects, threads, attachments, unread); W2 re-shots in Playwright.
- ClamAV still deferred to 1h (`av_status=skipped`). No live mailboxes; `REAL_IMAP_TEST_*` still skipped.

## [Unreleased] — Phase 1d: list & reading
### Added
- Threads, lazy message bodies, attachments and `user_settings` (migration `0006`); local file storage via
  `STORAGE_PATH` (ADR-006). HTML sanitized with `nh3`; remote images rewritten to a placeholder.
- Message API: list (Zoznam / Konverzácie), detail with body fetch, flags, bulk (incl. Vybavené), snooze, assign,
  source (.eml), attachment download, prefs (list + UI theme/classic).
- Web W2 list (`MessageRow`, filters, pagination, Výber / Konverzácie / Možnosti W2o), reading pane W2c (Roundcube
  toolbar; Reply/Forward disabled until 1e), bulk bar W2e, print W2m, source W2n, dark mode and Klasické zobrazenie.
- Tests: sanitize, threading, parse, message list/prefs/snooze; vitest for rows + date format; IMAP integration
  against Dovecot (`tests/integration/test_imap_messages_1d.py`: list, thread, body, attachment — fictional mail
  only). Real-server suite still skipped without `REAL_IMAP_TEST_*`. Playwright shots for W2 / W2c / W2e / W2o /
  W2m / W2n (light, dark, Klasické).

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
