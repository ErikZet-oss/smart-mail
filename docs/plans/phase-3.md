# Phase 3 plan — Money read, mock first (#144)

**Status:** **draft — waiting for Erik's approval.** No Phase 3 code is written until the plan is approved. After
that, work goes milestone by milestone, and each milestone stops for review.

Scope and acceptance: CLAUDE.md §7, §12 Phase 3. Binding behaviour: `docs/MONEY_API.md` (§1–§8, §5.1–§5.4, §5.10).
Screens: `docs/SCREENS_SPEC.md` / `docs/FIGMA_MAP.md` (W3b, M10, W8b, M13, E2, W9a, W12-13a–f). Settings:
`docs/SETTINGS_SPEC.md` §13 (Phase 3 section per CLAUDE.md §10).

**Priority rule (as in Phase 2):** pilot bugs and Phase 1/2 acceptance blockers always come first.

## Guards for the whole phase

- **Read-only.** The only "write" in this phase is the REST `Activity` after an approved send (§5.1, §5.2). It is
  behind the 13a „Zápisy do Money povolené“ switch (default off) and runs against the mock until Erik approves the
  TEST agenda.
- **`MONEY_BACKEND=mock`** everywhere until Erik says otherwise. `MONEY_AGENDA_LABEL=TEST` is mandatory. The bridge
  refuses to start with `MONEY_BACKEND=api` and `MONEY_AGENDA_LABEL≠TEST`, unless an explicit
  `MONEY_ALLOW_PROD=true` is set (that variable is itself an „Otázka pre Erika“, not part of this plan).
- **The PRODUCTION agenda is forbidden** without Erik's explicit approval.
- **Mock data is fictional:** companies `*.example`, IČO that fail the checksum or come from a reserved test range,
  and generated invoice numbers. No real companies, persons or documents.
- **Never guess a field or enum.** Every query is validated against `bridge/schema/graphql_schema.json` in CI
  (`tools/validate_graphql.py`), and every REST path against the swagger files. Anything marked **[PROBE]** waits for
  `probe_output/report.md` (see the table below).
- Only the bridge holds Money credentials. The main app talks to it over HMAC only, and there is no generic GraphQL
  proxy (MONEY_API §6).
- **Money offline never breaks mail.** Every Money surface has a „Money nedostupné“ state (Figma frames exist). Sync
  failures are logged and retried; mail, AI triage and drafts keep working.
- `FEATURE_MONEY=false` stays the default on the pilot VPS until Erik switches it on.
- No floats for money: `Decimal` end to end, `numeric` columns, decimals as strings in JSON. The CI grep for
  `float(` also covers `bridge/app` and `app/money`.

## What is already there

- `bridge/` is a skeleton: FastAPI `main.py`, `config.py`, `/healthz` test, Dockerfile, compose service on
  `http://bridge:8100`.
- `bridge/schema/graphql_schema.json` (135 types) and `swagger_v1.json` / `swagger_v2.json` are in the repo. I checked
  that the queries Phase 3 needs exist with `Filter/From/Count/ChangeFrom`: `IssuedInvoices`, `Companies` / `Company`,
  `ReceivedOrders`, `IssuedDeliveryNotes`, `Articles`, `ArticleSuppliers`, `Version`, and the codebooks.
- The REST paths needed also exist: `IssuedInvoice/{id}/Report/{reportId}`, `Person`, `Activity`.
- **Missing:** `probe_output/` (report.md, orders.md, branches.md), the `money_*` / `email_company_links` tables, the
  `app/money/` package, and the bridge client in the main app.

## Milestones (one PR each, stop for review after each)

| # | Milestone | Screens / surfaces | Content |
|---|---|---|---|
| **3a** | Bridge core + mock | — (bridge only) | Pydantic models (hand-written for the ~25 types used, checked against the schema); `filters.py` filter builder with unit tests per operator and `hypothesis` (no unsafe value can produce extra `~ # \| ( )`); `gql_client.py` + `rest_client.py` (token cache `expires_in − 60 s`, single-flight refresh, one retry on 401, paging `Count ≤ MONEY_PAGE_SIZE`, never retry a mutation); `queries/*.graphql`; HMAC auth (key id + timestamp + body sha256, ±5 min, replay cache); read endpoints from MONEY_API §6 needed in Phase 3 (`/healthz`, `/sync/*`, `/companies/{id}…`, `/invoices/issued/search`, `/invoices/issued/{kind}/{id}/pdf`); `mock.py` with the fictional seed from MONEY_API §8 (the Phase 3 part: 20 customers, 300 issued invoices of which some are overdue, proformas, persons, activities, codebooks, a valid one-page PDF); **one contract test suite** run against the mock in CI and against the TEST agenda manually with `--money-live` |
| **3b** | Read cache + sync | W12-13a Prepojenie, W12-13e Synchronizácia | **Migration 0018 (Otázka 1):** `money_companies` (+ e-mails), `money_persons`, `money_codebooks`, `email_company_links`, `money_sync_state` (cursor per entity). `money_articles`, `money_article_suppliers` and `money_price_history` are needed only from Phase 4 and are not created now. `app/money/bridge_client.py` (HMAC, timeouts, circuit breaker → „Money nedostupné“); `cache_sync.py`: ARQ cron every 15 min with `ChangeFrom`, nightly full, codebooks daily; 13a status card (bridge, agenda TEST/OSTRÁ, API version, latency, last sync, „Otestovať“); 13e last runs and a manual „Synchronizovať teraz“ (admin) |
| **3c** | Sender → company + Zákazník panel | W3b (karta firmy, nespárovaný odosielateľ), M10 | Matching per MONEY_API §5.4: person e-mail 0.98 → company `Email`/`SeznamSpojeni` 0.95 → IČO from the signature 0.9 (mod-11 check) → same non-free-mail domain 0.7 (confirm once) → `email_company_links`. Threads get `money_company_id`. „Priradiť k firme“ (search in the cache), and confirmation is audited. „Založiť firmu“ is a write → **Phase 4**: only a disabled button with a tooltip. Panel: company header, receivables summary, last orders and deliveries, persons, activities |
| **3d** | invoice_attach | AiSuggestionCard (typ faktúra), W12-13b Tlačové zostavy | AI plan tool `find_invoice` (MONEY_API §5.1 search cascade); suggestion type `invoice_attach` = reply draft with the **original Money PDF** (never rendered by us). **Blocking guard: `Firma_ID` == company of every external recipient** (re-run on approve; 409 `recipient_not_document_owner`). One customer per suggestion; number/fact check against Money data. Proforma via REST `PrepaymentIssuedInvoice`. Report id per language from 13b (fallback SK); „Vyskúšať PDF“. Autonomy is capped at level 2 (external send). Acceptance: 10 invoice requests end to end on the mock (and later TEST), 0 wrong-recipient sends |
| **3e** | Receivables + Upomienky | W8b (+ kontrola návrhov, odoslané, načítava sa, prázdne, chyba), M13, E2 | `/companies/{id}/receivables` (`UhradyZbyva > 0`, overdue = `DatumSplatnosti < today`); W8b table of customers with overdue invoices; a reminder = compose draft from E2 (tone Zdvorilá / Dôrazná, table, bank details from Money, invoice PDFs attached), always approved and sent by a person; no change of reminder dates in Money |
| **3f** | Activity log + 13d | W12-13d Aktivity | After an approved send of `invoice_attach` / a reminder to a linked company: REST `POST Activity` (type from 13d, mapped from `TypeOfActivity`, never a guessed GUID). Behind the 13a writes switch + the 13d switch; idempotent (`SMID:` in the text, check before create), never auto-retried; failures go to a retry list for the admin, not silently |
| **3g** | Zákazník 360 + global search | W9a (Prehľad, E-maily, Doklady, Kontakty a aktivity, načítava sa, Money nedostupné), M10 | `/contacts/company/:moneyId` with tabs; e-mails = threads with `money_company_id`; Doklady = invoices, orders, deliveries (read); Money group in global search and the command palette (companies by name/IČO from the cache, invoices by number live via the bridge) |
| **3h** | Bridge deployment (ADR-016) | — | **Implementation only after Erik's answer (Otázka 2).** See the „Deployment“ section |

13c (Predvolené hodnoty dokladov) and 13f (Vrátenie zápisov) belong to write features → Phase 4. In Phase 3 they are
only listed in the 13 navigation as „Bude dostupné vo fáze 4“, or hidden (Otázka 4).

## What waits for the schema / probe ([PROBE])

| Item | Waits for | Until then |
|---|---|---|
| Escaping of `~ # \| ( )` in filter values | probe / implementer | reject unsafe values (`UnsafeFilterValue`) — never escape |
| Date format in filters | probe | `YYYY-MM-DD` in the mock; contract test on TEST confirms |
| `Person.Parent_ID` = company | probe | mock models it; matching step 1 off on `api` until confirmed |
| Report GUIDs per language (invoice, proforma, credit note) | implementer (MONEY_API §9 q2) | 13b fields empty → „PDF nie je nastavené“ instead of a PDF |
| `TypeOfActivity` value for „E-mail odoslaný“ / „Upomienka odoslaná“ | probe / codebook | 13d select from the codebook, no default |
| Page limit and performance of `ChangeFrom` | probe | `MONEY_PAGE_SIZE=200` |
| Rights of the API role | implementer (MONEY_API §9 q3) | read only |

Before `MONEY_BACKEND=api` on TEST: run `tools/money_probe.py` → `probe_output/report.md` into the repo (no
customer data, the probe already redacts it), compare it with the plan and fix the mock.

## Deployment (ADR-016 draft — Otázka 2)

Money S4 runs on a **physical server in the office, 24/7**. The app runs on the VPS (ADR-010).

Proposal:
- The **bridge runs on the office server**, in the LAN next to Money. It is the only place with Money credentials;
  Erik enters them on the server himself (never in GitHub or chat).
- **Connection app ↔ bridge: Cloudflare Tunnel** started from the office (outbound only). There is no open port in
  the office and none on the VPS for the bridge.
  - Hostname e.g. `money-bridge.<domain>` protected by **Cloudflare Access with a service token**. The app sends
    `CF-Access-Client-Id/Secret` from `.env`.
  - **HMAC** stays on top, so a leaked Access token alone is not enough.
- The bridge listens on `127.0.0.1:8100` on the office server; `cloudflared` forwards to it.
- **Variant A — Docker** (Linux, or Windows with Docker Desktop / WSL2): `deploy/bridge/docker-compose.yml` with
  `bridge` + `cloudflared` (pinned images), `.env` `chmod 600`, `install-bridge.sh` / `update-bridge.sh`, health
  check.
- **Variant B — Windows service** (no Docker): Python 3.12 + uv, the bridge as a service through **NSSM** or
  **WinSW**, `cloudflared service install`, a PowerShell `install-bridge.ps1`, logs into a file with rotation.
  NSSM/WinSW is a new tool → part of Otázka 2.
- The app checks `/healthz` every minute. When the bridge is down: the 13a status card shows „Money nedostupné“
  and an audit entry is written; mail keeps working.
- Alternatives considered: WireGuard VPN office ↔ VPS (needs a router change in the office); opening a port with
  TLS + IP allowlist (open port, rejected); the bridge on the VPS with Money reachable via the tunnel (Money
  credentials would leave the LAN, rejected).

## Acceptance (CLAUDE.md §12 Phase 3)

| Criterion | How we prove it |
|---|---|
| 10 real invoice requests end to end, 0 wrong-recipient sends | first on the mock (fictional fixtures, e2e + unit tests of the owner guard), then on the TEST agenda once Erik approves `MONEY_BACKEND=api` |
| Money offline does not break mail | e2e with the bridge stopped: list, reading, compose, send, AI triage work; Money surfaces show „Money nedostupné“ |
| Contract tests | the same suite green on the mock (CI) and on TEST (manual, `--money-live`) |
| Schema drift | `tools/validate_graphql.py` + swagger path check in CI |
| No floats / strict typing | CI grep + mypy strict for `bridge/` and `app/money` |
| Screens match Figma | side-by-side for W3b, M10, W8b, M13, E2, W9a, W12-13a/b/d/e (Figma MCP is not reachable from this session at the moment — 403; if it stays down, screenshots go to Erik for review) |

## Order of work

1. 3a → 3b → 3c are strictly sequential (models → cache → matching).
2. 3d needs 3c (recipient ↔ company). 3e and 3g can run after 3c in parallel with 3d.
3. 3f after 3d/3e (it hooks into their send).
4. 3h in parallel any time after Erik answers Otázka 2. Real-API work (`MONEY_BACKEND=api`) starts only after 3h +
   probe report + Erik's approval.

## Non-goals in Phase 3

- Any Money document write (delivery notes, orders, complaints, companies, persons) → Phase 4.
- Offers, stock, customer prices → Phase 6 (stock and prices are only needed for offers and orders).
- Order status sync / „Tovar odoslaný“ → Phase 5.
- Rendering invoices ourselves → never (DOCUMENTS_SPEC §6).

## Risks

- **The real schema may differ from what the mock assumes.** Mitigated by validating every query against the
  introspection schema and by the shared contract suite. The probe report is the gate before `api`.
- Office server availability (power, Windows updates) → health checks + „Money nedostupné“; mail is unaffected.
- Wrong recipient for an invoice PDF → blocking owner guard re-run at approval, tests per path.
- Cache staleness (15 min) → live re-check of the invoice owner and balance at approval.

## Otázka pre Erika

1. **Data model (CLAUDE.md §0 — changing the model after Phase 1 needs approval):** milestone 3b adds migration 0018
   with `money_companies`, `money_persons`, `money_codebooks`, `email_company_links` and `money_sync_state`, as
   listed in CLAUDE.md §4. `money_sync_state` is a small helper table for the sync cursor. Is that OK?
2. **Bridge deployment:** do you agree with the bridge on the office server + Cloudflare Tunnel + Access service
   token + HMAC? What OS runs on the server (Windows Server / Linux), and is Docker allowed there? If it is Windows
   without Docker: do you approve NSSM (or WinSW) as a new tool for the Windows service?
3. **Probe:** can you run `tools/money_probe.py` on the TEST agenda and add `probe_output/report.md`? Until then
   everything runs against the mock.
4. **Settings 13c and 13f** (write features): hide them in Phase 3, or show them as „Bude dostupné vo fáze 4“?
