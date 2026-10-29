# Changelog

All notable changes. Format: Keep a Changelog; versions follow the build phases (CLAUDE.md §12).

## [Unreleased] — Pilot #33: branch logins and persons in Settings 10/11

- Settings 10 (W12-10): account list with search, „Vytvoriť“ (e-mail + Osobný: meno, priezvisko, rola /
  Pobočkový: pobočka), detail with Typ účtu, Pobočka, Rola, Stav. `kind=branch` without a branch → 422
  `branch_required`. Converting a personal login („Zmeniť na prihlásenie pobočky“, confirm) deactivates the
  placeholder person (never deletes it) and logs the account out everywhere, so the next login shows „Kto ste?“.
- No change may leave no active admin who can sign in → 409 `last_admin` (account kind/active/role, person
  role/active, person removal, link).
- Settings 11 (W12-11): „Pridať pobočku“; Údaje form (name, branch mailbox, address, phone, hours) shows which
  login uses the branch mailbox and offers „Prepojiť prihlásenie s pobočkou“ (creates the branch login when the
  mailbox has none). Osoby: table + drawer to add/edit (meno, priezvisko, funkcia, telefón, mobil, rola, vedúci,
  aktívna) and „Odstrániť osobu“ — a person with history (audit, own login, compose draft) is deactivated; any other
  reference (e.g. a session) also falls back to deactivation instead of a 500; the last active person stays (409).
- Audit for every change with `before` / `after` (kind, branch, role, active; person fields), never secrets
  (`settings.user_created|user_patched|branch_login_linked|person_created|person_saved|person_deleted|deactivated`).
- CLI: `app.models` registers every table (fixes `NoReferencedTableError` for `branches.mailbox_id` in
  `add-person` / `add-account --branch`); `add-account … --branch NAME --convert` converts an existing personal
  login. Alembic uses the same registry.

## [Unreleased] — Pilot #41: visible sync errors, isolated bad messages, first-sync progress

- Any unexpected exception in a mailbox sync sets `sync_state = error` and `sync_error` = the exception class
  (max 64 chars, never server text). `sync_error = "unexpected:<Class>"`; W2 shows „Synchronizácia schránky {email} zlyhala – správca bol
  upozornený“ (Figma G6), an unreachable server keeps „Nepodarilo sa načítať priečinok“. The existing
  sync notification fires, the next good sync clears it.
- Envelopes are committed before threading. Threading runs in batches of 500 inside a SAVEPOINT; a failing batch
  is retried one message per SAVEPOINT, so one bad message stays unthreaded (visible in Zoznam) and the rest go on.
- Threading no longer queries per message (thread index in memory, bulk insert/update, one aggregate count update):
  20,000 envelopes thread in ~25 s instead of ~460 s. Load test in CI.
- `GET …/folders` returns `sync.loaded` / `sync.total`; W2/M2 show „Načítava sa schránka… 12 400 / 25 000“.
- Reading pane (W2c/M3): a 500 on the message shows the error state „Nepodarilo sa načítať správu.“ with the
  reference code and „Skúsiť znova“ instead of an endless skeleton (no redirect to W16c).

## [Unreleased] — Pilot #30: forward keeps the original attachments

- Poslať ďalej copies the original message's ordinary attachments onto the draft
  (same stored file, not a second copy). Infected files are left behind. Files not
  yet scanned (`skipped` / `error`) stay, with the same antivírus label as in the
  reading pane. The user can remove a chip before send.
- Send re-reads the antivirus status of the stored file (the draft copy can be
  stale). `infected` is 409 `attachment_infected` with the file name and cannot be
  forced. `pending` warns „Príloha ešte nebola skontrolovaná antivírusom“ and the
  user confirms. A missing file is 409 `attachment_missing`, not an empty attachment.
  The compose chip shows the current status. The undo-delay job runs the same check.
- Autosave to Koncepty skips the IMAP copy when a forwarded file is infected or
  missing (`compose.draft_imap_skipped`, draft id and code only). The local draft
  still saves and the chip shows the status.

## [Unreleased] — Pilot #35: person switch refreshes the cache

- Choosing or switching a person drops cached queries other than the signed-in
  profile, the Kto ste? list and an open compose draft, then reloads what is on
  screen. Settings, lists and permissions follow the new person. The open draft
  keeps its signature.
- A successful login, and a 401 that sends the user back to Prihlásenie, clears
  the whole query cache so the previous person is not shown again.

## [Unreleased] — Pilot #31: signature images survive in Gmail

- Sending a message rewrites images in the whole HTML. `data:` PNG/JPEG/GIF/WebP
  and uploaded signature files become inline CID parts. `/logo-smart.svg` and
  `/logo-smart.png` become the SMART logo as PNG (never SVG). An image-proxy
  URL becomes the original `https://` address. `https://` stays. `http://` and
  any other src are removed; the log records how many, not the address.
- `src` is matched only as a whole attribute, so a `data-sm-keep-src` stamp
  before it is not rewritten. The sent HTML drops `data-sm-*`, `data-cid` and
  `srcset`. An unquoted or empty `src` is cleared and counted.

## [Unreleased] — Pilot #28: signature and quote stay formatted in Napísať

- Compose (W4) keeps the signature as a TipTap atom `SignatureBlock`. Tables, colours
  and images render like the settings preview and are not editable in the text.
  The Podpis button still opens the per-message editor. Changing the identity
  replaces the block.
- A reply or forward keeps the original message as a `QuotedMessage` atom.
  On send the server rebuilds the signature with `render_signature` and the quote
  from the stored message. Signature or quote HTML from the browser is ignored.
- The user's own text uses Underline, colour, highlight, alignment, link, table
  and inline CID images, so that formatting is not rewritten on save.
- A reply or forward quote is taken from the stored raw message and sanitized
  without rewriting remote images, so `https://` URLs stay. `cid:` images from
  that message are attached as related parts. W4 has no „Preposlať s prílohami“
  control, so ordinary attachments are not copied.

## [Unreleased] — Pilot #24: Roundcube signature editor (D22, SETTINGS 03a / 11c)

- Identity signature (03a) and the per-message signature (W4e) use the TipTap editor:
  bold, italic, underline, alignment, font, size, colours, link, table, image,
  horizontal rule, special characters, and a „Zdrojový kód“ dialog (Vložiť / Zrušiť).
- Uploaded PNG/JPG/GIF, at most 5 images, 200 kB and 2000×2000 px each, are stored
  outside the HTML and sent as inline CID. SVG is converted in the browser; the server rejects it.
  https image URLs in our own signature stay, stamped by the server, and the reading pane loads
  them through the signed image proxy. A received message cannot opt out of remote-image blocking.
- Branch template (11c): language tabs SK / CZ / EN / DE, variable chips, presets „Karta“ and
  „Text“, live preview. A shared branch mailbox in 03a shows only the preview and a link to
  section 11. Slovak is required. Unknown variables are rejected. Saving reports what nh3 stripped.
- Colours in the default „Karta“ come from `design/tokens.css`.

## [Unreleased] — Pilot #23: send confirmation, answered/forwarded, immediate Sent sync

- After Send, toast „Odosiela sa… Späť“ for the undo window; Späť cancels the send. The toast
  stays after compose closes (poll up to 60 s, W4 and M4).
- After SMTP, toast „Správa bola odoslaná.“ Click opens that message in Odoslané.
- On failure, the existing Slovak reason plus „Otvoriť koncept“. If APPEND fails, toast
  „Správa bola odoslaná, ale nepodarilo sa ju uložiť do Odoslané.“ and do not resend.
- Reply stores `\\Answered` (IMAP + list icon); forward stores `$Forwarded`.
- Sent APPEND uses the folder sync already knows (`special_use=sent`). A mailbox is created
  only when none exists, with the NAMESPACE prefix (`Sent` or `INBOX.Sent`). That folder is
  synced immediately.

## [Unreleased] — Pilot #18 (before 2c): ManageSieve, shell errors, AI gate, readyz

- **B1**: ManageSieve via `asyncio.to_thread` (connect 5 s, overall 10 s); Redis cache „Sieve unavailable“ 10 min;
  W12-05/06 Slovak banner, no 500. Black-hole Sieve must not stall `/readyz` or the message list.
- **B2**: AppShell loading + 10 s timeout → W16-style error with „Skúsiť znova“; React error boundary around the shell.
- **B3**: Hide AI TRIEDENIE when `ai_enabled=false` or no Anthropic key; `/ai/views/*` returns empty, never 500.
- **B4**: `/readyz` own 2 s budget + fresh Redis probe; docker healthcheck `curl --max-time 3`.
- **B5**: Rewrite `cid:` images to `/api/mail/mailboxes/{ref}/attachments/{id}/inline` (image/*, ACL, infected→403).
- **B6**: Signed `GET /api/mail/image-proxy` for remote images; CSP keeps `img-src` without `https:`; SSRF blocks
  non-global IPs (`not is_global`, IPv4-mapped unwrap) after async DNS; connect pins the verified IP (Host+SNI);
  stream abort / Content-Length > 5 MB → 413; purpose-separated HMAC key; SVG→415; honors `remote_images`
  never/known/always.
- **B9**: `Content-Disposition: attachment` is never treated as inline even with Content-ID (Gmail); hide as inline
  only when HTML references the part via `cid:`.
- **B10**: Keep non-text parts without Content-Disposition (Apple Mail / Outlook); named second text/html|plain and
  `message/rfc822` are attachments. Nightly job re-parses stored raw for `has_attachments` messages.
  Fixtures under `fixtures/mail/` (fictional).

## [Unreleased] — Pilot #20 (blocker): SMTP AUTH + Sent APPEND + draft IMAP

- Outbound SMTP uses mailbox credentials (`credentials_for`, Fernet D27) and `mailbox.smtp_*` (else `SMTP_*` env);
  MAIL FROM = identity address; 535 → `auth_failed` + mailbox state like IMAP.
- After successful SMTP, APPEND to SPECIAL-USE `\Sent` (fallback Sent/Odoslané) with `\Seen`; APPEND failure never
  re-sends.
- Compose autosave mirrors the draft to IMAP `\Drafts` / Koncepty (APPEND new, delete previous UID).
- `imap-test` exposes AUTH-required SMTP on :587 (bridge → LMTP); CI test: no auth fails, with auth succeeds + Sent.
- W4 shows a clear Slovak error on `failed` instead of staying on „Odosiela sa…“.


## [Unreleased] — Phase 2b: classify + AI views (W2f)

- Deterministic rules first (List-Unsubscribe, carriers, internal domains, ISDOC/UBL, DMARC candidate);
  classify JSON schema (AI_ASSISTANT §4); language detection (sk/cs/en/de/pl/hu/other).
- Pipeline classifies mail after `ai_enabled_at` only; private / special folders skipped; budget gates live LLM.
- W2f AI triedenie: `/mail/:mailbox/view/:category`, folder-column counts, list badges + AI summary toggle
  (SETTINGS 07 + list options); Klasické zobrazenie hides triage.
- `SecurityBanner` for DMARC / SPF / display spoof / IBAN-change notes (no reply suggestion cards — that is 2c).
- Slovak strings in `web/src/i18n/sk.json`; Playwright vs Figma `26:21256` / `26:21793`.
- Review (PR #17): always record paid `AiRun` (ok / invalid_output / error) with real tokens/latency/cost;
  Anthropic API errors leave mail unclassified (retry max 3); neutralize `</untrusted_email>` escapes in
  prompts; classify via Anthropic tool use / JSON schema (regex last resort); display-spoof only vs
  company / person names (no false positive for “Smart Electronics”).

## [Unreleased] — Phase 2a: AI foundation (provider, schema, pipeline gates)

- **D31 / ADR-011**: Claude API (`LLM_PROVIDER=anthropic`); Bedrock interface stub only. ADR records official
  Anthropic data handling (processing location, retention, training, DPA) and cost per 1 000 mails for classify/draft.
  Model ids only from env — never `latest`.
- Pricing: exact model-id table (Haiku/Sonnet/Opus 5.5, Haiku 4.5); unknown → highest rate + warning; Haiku 4.5 ≠ 5.5.
- Budget: Europe/Bratislava day; checked **before every** LLM call with that call’s estimate (batch stops at limit).
- Unscanned attachment: process body text, skip file, note `attachment_unscanned` → `ai.notes.attachment_unscanned`.
- Anthropic client: ~60 s timeout, max 2 retries, one client per process.
- `LLMProvider` + `NullLLMProvider` (no key); `ai_runs` / `classifications` / `ai_suggestions` / `feature_flags`;
  `mailboxes.ai_enabled_at`; AI off by default until enabled (sets `ai_enabled_at`).
- Worker hook after sync gated by `ai_enabled_at`, D21 folders, Message-ID idempotency; daily budget; `ai_shadow_mode`
  seeded. **No classify UI / suggestion cards** (2b+).
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
