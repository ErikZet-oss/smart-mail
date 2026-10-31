# Changelog

All notable changes. Format: Keep a Changelog; versions follow the build phases (CLAUDE.md §12).

## [Unreleased] — Phase 3c: sender → company, Zákazník panel (#144)

- **Sender matching** (`app/money/matching.py`, MONEY_API §5.4) runs on the read cache when the panel opens. The steps, in order:
  - a confirmed link (1.0);
  - a Money person e-mail (0.98);
  - a company `Email` / `SeznamSpojeni` (0.95);
  - an IČO from the mail body with a mod-11 check (0.9);
  - the same company domain (0.7, a person confirms it once; never free-mail or our own domains).
- Two companies on one step → no guess: the candidates are offered. For our own outgoing mail the first external recipient is used.
- **API** `/api/money/…` (404 `money_disabled` without `FEATURE_MONEY`):
  - customer of a message;
  - company card;
  - cache search;
  - „Priradiť k firme“ link / unlink (person with a role other than viewer, audited; internal addresses refused).
- The card loads receivables, orders, deliveries and activities from the bridge **one by one**: one part down („Money je teraz nedostupné“ / „čaká sa na test prepojenia“) never hides the others.
- Bridge client: 501 `waiting_for_probe` is not counted as an outage, and 404 company → none. The contract fixture now includes orders, deliveries and activities.
- **W3b / M10 Zákazník panel**:
  - toolbar button „Zákazník“ (only with `FEATURE_MONEY`), `?panel=customer`;
  - 380 px panel on desktop, full screen on mobile;
  - `CustomerCard`: header (IČO, IČ DPH, code, discount, splatnosť), KPIs „otvorené / po splatnosti“, invoices, last orders and delivery notes, activities, contacts;
  - not matched → search the cache and assign. „Založiť firmu v Money“ is disabled until Phase 4.
- Review (#160): a message in someone else's private folder answers 404 `message_not_found` (same `visible_to` rule as search and export); `dump.rdb` removed and ignored.
- **No data model change:** the company is evaluated on the fly instead of storing `threads.money_company_id` (not in the approved migration 0018).

## [Unreleased] — fix: duplicate key in sk.json

- `settings.branches.signature` was defined twice („Podpis“ from #140 and „Šablóna podpisu pobočky“); JSON keeps the last one silently. The unused #140 entry is removed and a vitest check now fails on any duplicate key inside one object of `sk.json` (found by the agent in #158).
## [Unreleased] — Phase 3b: Money read cache + sync (#144)

- **Migration 0018** (approved by Erik in #150) adds `money_companies`, `money_persons`, `money_codebooks`, `email_company_links` and `money_sync_state`.
  - These tables are a read cache only; nothing is written back to Money.
  - Company e-mails (`Email` + `SeznamSpojeni`) are stored lower-cased for the sender matching in 3c.
- **`app/money/bridge_client.py`**: the main app's only way to Money.
  - HMAC-signed GETs, the same signature as the bridge (shared test vector).
  - After 3 failures in a row a circuit breaker opens for 60 s; every failure becomes „Money nedostupné“, and mail keeps working.
  - The contract fixture `fixtures/money/bridge_contract.json` comes from the bridge mock: the bridge suite fails on drift, and the app parses the fixture with `app/money/schemas.py`.
- **`app/money/cache_sync.py`**:
  - companies sync by `ChangeFrom` delta;
  - persons and codebooks sync in full (the REST delta is [PROBE]);
  - a nightly full run marks rows that disappeared as inactive and never deletes them;
  - the cursor moves only after a run without errors;
  - the last 20 runs are kept per entity, with counts and error codes only, never Money data.
- **Worker `money_sync`**: checked every 5 min. It does what Settings 13e says is due, runs only with `FEATURE_MONEY=true`, and one run at a time (Redis lock).
- **Settings 13 Money S4** (admin, shown only with `FEATURE_MONEY`):
  - **13a Prepojenie**: bridge status card with agenda, API and bridge version, latency, last sync and „Otestovať“, plus row counts of the cache. Writes are shown as off.
  - **13e Synchronizácia**: interval 5/15/30/60 min (audited), „Synchronizovať teraz“, history.
  - 13c / 13f stay hidden in Phase 3 (Erik, #150); 13b / 13d come with 3d / 3f.

## [Unreleased] — #156 AI suggestion cards collapsed by default

- The reply suggestion card and the Prehlásenie o zhode card start as one line (~48 px): AI icon, title, category · language, check status (✓ / ⚠ N / ⛔), the first ~80 characters, „Zobraziť návrh“.
- „Pripraviť koncept“ / „Pripraviť prehlásenie…“ appear only after expanding; „Zamietnuť“ (×) also works collapsed.
- Click, Enter or Space expands (`aria-expanded`); „Zbaliť“ in the expanded header gets the focus.
- No Figma frame for the collapsed state (built from the existing card, Erik's approval in #156). The optional setting „Návrhy zobrazovať rozbalené“ is left out.

## [Unreleased] — fix: supplier invoices classified as invoice requests

- Pilot 2026-10-30: „Faktura E3/2026/19608“ from a supplier with `E3_126_19608.pdf` + `.csv` (body only a bank-details note) was classified „Žiadosti o faktúru“ and got a reply suggestion. New deterministic rule `supplier_subject_attachment`: a new external mail (no `Re:`/`Fwd:`) whose subject starts with Faktúra/Faktura/Invoice/Rechnung/Dobropis/Dodací list/Delivery note/Lieferschein and carries a PDF/ISDOC/XML/CSV is a supplier document, without an LLM call. It runs after the DMARC check, so a spoofed „Faktura“ is still flagged. The non-decisive PDF-name hint no longer short-circuits the later checks.
## [Unreleased] — fix: „Šablóna podpisu pobočky“ label on the person's hand signature

- Pilot 2026-10-30: the person's hand-signature upload (#140) reused the label key `settings.branches.signature` = „Šablóna podpisu pobočky“ (the e-mail signature template), so Erik uploaded the signature in the wrong place. New labels „Vlastnoručný podpis (pre doklady)“ and „Pečiatka (pre doklady)“, with help texts that say they are never used in e-mail signatures.

## [Unreleased] — Phase 3a: Money bridge core + mock (#144)

- The bridge answers the Phase 3 read endpoints of MONEY_API §6, all behind HMAC (key id + timestamp ±5 min + body hash, replay refused):
  - `/sync/companies|persons|codebooks/{name}` (paging with `from`/`count`, `since` for delta);
  - `/companies/{id}` and its `/receivables`, `/orders`, `/deliveries`, `/activities`;
  - `/invoices/issued/search` (MONEY_API §5.1 cascade: number → VS → Odkaz → company + dates → digits);
  - `/invoices/issued/{invoice|proforma}/{id}/pdf?report_id=` (original Money PDF; the report id comes from Settings 13b).
- Two backends behind one interface and one Pydantic contract:
  - **mock** (fictional seed: 20 companies on `*.example`, IČO with a wrong check digit, 320 invoices, orders, deliveries, activities, codebooks, a valid one-page PDF);
  - **api** (token cache with single-flight refresh and one retry on 401, GraphQL from `bridge/app/queries/*.graphql`, REST only for PDF and persons, JSON parsed without floats).
- Filter builder (MONEY_API §7) rejects `~ # | ( )` in values instead of escaping them; unit + property tests (hypothesis).
- **Contract suite** `bridge/tests/test_contract.py` runs on the mock in CI and on the TEST agenda with `--money-live`.
- Not guessed, answered 501 `waiting_for_probe` on the real API: REST activity filter by company (also proforma search). `Stav` / `TypDokladu` / `Vyrizeno` are passed through raw.
- Safety: `MONEY_BACKEND=api` refuses to start unless `MONEY_AGENDA_LABEL=TEST` and a non-dev `BRIDGE_HMAC_SECRET` are set. Read-only (no mutation in any query; a test checks it). Money down → 503 `money_unavailable`, `/readyz` 503.
- CI (bridge job): schema drift check of queries and docs blocks (`tools/validate_graphql.py`), and a `float(` ban for `bridge/app` and the money/order packages.

## [Unreleased] — fix: Prehlásenie o zhode for a personal account / several branches

- Pilot 2026-10-30: Erik (personal account on eshop@, no branch) could not issue — 422 `branch_required`, and the dialog had no way to pick a branch. New `GET /api/documents/conformity/branches` (admin: all branches; sales: own + „Pôsobí aj na pobočkách“; with a `ready` flag = stamp + manager signature), and the dialog shows a „Pobočka“ select when more than one branch is offered. The SK error text now says how to get a branch.
## [Unreleased] — Phase 3 plan (#144)

- `docs/plans/phase-3.md`: Money read with a mock bridge first — milestones 3a–3h, [PROBE] items, bridge deployment draft (ADR-016), acceptance, questions for Erik. Waiting for approval; no code yet.
## [Unreleased] — fix(#121): the CI `npm test` flake found

- The #145 annotation showed it: every test passed, but vitest reported an unhandled `ReferenceError: document is not defined` from a ProseMirror `DOMObserver` timer — `aiText.test.ts` created TipTap editors and never destroyed them, so a timer fired after jsdom was torn down. The editors are now destroyed after each test.

## [Unreleased] — Phase 2 close-out report

- `docs/phase2-closeout.md`: milestones 2a–2f, acceptance status, gates, open items and what is needed from Erik.

## [Unreleased] — #143 „Zmeniť kategóriu“ and „Znova zaradiť (AI)“

- Review (#148): „Znova zaradiť (AI)“ — one message or in bulk — follows the same rule as the pipeline (`message_eligible_for_ai`): a private folder, Koncepty/Odoslané/Kôš/Nevyžiadaná pošta and mail from before `ai_enabled_at` answer 409 `ai_not_allowed_here` without a model call; the bulk job counts them as `skipped`. „Zmeniť kategóriu“ by hand stays allowed everywhere.
- W3 Viac › **„Zmeniť kategóriu…“** (sales/admin with an active person) offers the enabled 17c categories. The choice is stored on the existing classification: `category` plus `payload.corrected_category`, `corrected_from` (the AI's answer, kept from the first correction), `corrected_by_person_id`, `corrected_at`. No new column. Audit `ai.category_corrected` with before/after. The message moves to the new AI view at once.
- **A person's correction wins:** the pipeline never touches a finished classification, and „Znova zaradiť“ answers 409 `category_corrected_manually`.
- W3 Viac › **„Znova zaradiť (AI)“** makes one classify call with today's prompt and 17c categories (an `ai_runs` row with purpose `classify`, within the daily budget, else 429). It replaces category, needs_reply and summary; on failure the old classification stays. Audit `ai.reclassified`. In an AI view, a selection of up to 50 messages → **„Znova zaradiť (AI)“** as one ARQ job (`reclassify_messages_job`), which stops when the budget is spent and skips corrected messages.
- Eval: `eval_cli run --labels-from corrections` scores people's corrections (label = their choice, predicted = the AI's answer; biased towards mistakes, so the random sample stays the main metric). `GET /api/settings/ai/usage` returns `corrected_30d`.
- `GET …/ai/categories?all=1` lists every enabled category, for the dialog.

## [Unreleased] — #127 part 2: delete the archived messages from the server, and check disk space first

- After the archive is downloaded, the export dialog offers „Vymazať správy zahrnuté v archíve…“. It confirms („Natrvalo vymaže N správ zo servera. Máte archív uložený?“) and needs the password (re-auth). It deletes **exactly the UIDs in the manifest**, per folder, with `\Deleted` + UID EXPUNGE (not the Kôš, so the quota is freed). Mail that arrived after the export stays.
- Guards, each tested:
  - only after the archive was downloaded (409 `export_not_downloaded`);
  - the stored archive must still match its sha256 (409 `export_archive_mismatch`);
  - once per archive;
  - a re-created folder (UIDVALIDITY changed) is skipped;
  - on a server without UIDPLUS, a folder that has other `\Deleted` messages is skipped (a plain EXPUNGE would remove them too).
- Review fixes (#134):
  - UIDVALIDITY fails closed: a missing value on either side skips the folder (`uidvalidity_unknown`).
  - „Downloaded“ is recorded only after the last block of the archive went out, so a broken download never unlocks the delete step.
  - A Redis lock per export (30 min) stops two deletes at once (409 `export_purge_running`).
  - The confirm dialog names the size and the folders.
- Audit `mail.export_purged` records the count, folders, skipped folders and the archive sha256; a sync is scheduled afterwards.
- Before an export starts (API and job), the free space of the temp directory is checked against the estimate × 1.1. Too little → 507 `export_no_space` with a Slovak hint to narrow the range (reviewer note on #130).
## [Unreleased] — #139 part C: AI suggestion for the Prehlásenie o zhode

- A mail classified `document_request` that asks for an atest 2.1 / prehlásenie o zhode (keywords in SK, CZ, EN and DE, ignoring case and diacritics) gets a card „Návrh: Prehlásenie o zhode (atest 2.1)“. The extract model prefills customer, document and products from the e-mail only; the e-mail is wrapped as untrusted, and budget and shadow mode apply. Numbers or codes that are not in the e-mail are flagged as a warning.
- The card has no approve: „Pripraviť prehlásenie…“ opens the issue dialog prefilled, and the person checks and issues it. Issuing from the card marks the suggestion approved with the final values (and whether the person changed the products). `POST /suggestions/{id}/approve` answers 422 for this type, so the AI can never issue. „Netreba“ rejects the card.
- Products from the invoice or delivery note in Money come with Phase 3.

## [Unreleased] — CI: name the flaky unit test (#121)

- `npm test` keeps failing on CI now and then, and the job log is not reachable through the proxy, so nobody can see which test fails. CI now also runs the vitest `github-actions` reporter: every failure becomes an annotation (test name, file, line), readable through the checks API. No retries.
- `formatMailDate.test.ts` built its times with a fixed `+01:00` but the code counts calendar days in the local time zone, so it failed in UTC+14. The test now uses local times and passes in every time zone tried (UTC, UTC+14, UTC−11, Bratislava).
## [Unreleased] — #139 part B: issue the Prehlásenie o zhode (atest 2.1)

- W3 Viac › „Vystaviť prehlásenie o zhode…“ opens a dialog: customer prefilled from the sender, document, place (default: the branch's town), date, and an editable products table. „Náhľad PDF“ shows the document without a number and stores nothing. „Vystaviť“ is the person's click (sales or admin of the branch, or covering it) and:
  - takes the next **`PZ-RRRR-NNNN`** (one company series, new each year, no gaps — a counter row in `org_settings` locked FOR UPDATE; tested with 6 issues at once);
  - renders the PDF (WeasyPrint port of Erik's template, `templates/print/conformity.html.j2`) with the **branch stamp and the branch manager's signature**;
  - stores the PDF with its sha256 in `conformity_declarations`;
  - **attaches it to a reply draft in Koncepty** and opens it. Sending stays with the person.
- Issuing is blocked without a branch stamp (`no_branch_stamp`) or a manager with a signature (`no_manager_signature`). A person of another branch gets 403 unless covering it; a warehouse role 403; a viewer read-only. Audit `document.conformity_issued` records number, branch, prepared_by, signer, document, item count and sha256, without customer content.
- Golden file `fixtures/documents/conformity_sample.{json,pdf,png}` with a fictional customer, stamp and signature (`tools/make_conformity_fixture.py`). Liberation Sans 2.1.5 is bundled so CI, the image and dev render the same.
- The stamp/signature size check no longer changes Pillow's global `MAX_IMAGE_PIXELS` (#140 review).
- SCREENS_SPEC (dialog W2-PZ) and DOCUMENTS_SPEC §5 updated.

## [Unreleased] — fix: stamp/signature upload showed only a generic error

- Pilot 2026-10-30: a stamp upload ended with „Zmenu sa nepodarilo uložiť.“ — `image_png_required` and `image_not_transparent` had no Slovak text. Both added; a test checks that every error code of the stamp/signature check has its text.
## [Unreleased] — fix: complaints in replies to e-shop notifications were missed

- Pilot 2026-10-30: „po otvorení zásielky … zistené množstvo 20 ks“, a reply to our „Odoslaná“ notification, was classified `other` with `needs_reply=false`, so no reply suggestion. The classify prompt now defines a complaint (missing/wrong quantity, wrong or damaged goods, defect, lost parcel — even without „reklamácia“) and says a reply to our automatic notification is judged by what the customer wrote. `needs_reply` got a description in the tool schema.

## [Unreleased] — #139 part A: Prehlásenie o zhode — data model, Pečiatka and Podpis

- Migration 0017 (approved by Erik): `branches.stamp_key`, `persons.signature_key`, and the table `conformity_declarations` (number unique, branch, prepared_by, signer, account, customer, document, items, place, date, PDF key, sha256, message/thread). Part B uses the table.
- Settings 11: „Pečiatka“ for a branch and „Podpis“ for a person. Both take a PNG with a transparent background, max 1 MB, scaled down to 1200 px. Upload and removal are ⚠ (admin + re-auth), audited as `settings.stamp_saved`/`stamp_removed` and `settings.signature_saved`/`signature_removed`. The images are never served publicly: there is only an admin preview with `no-store`, and no e-mail signature variable.
- ADR-015 records Erik's decisions (numbering, branch header, the manager signs, render with WeasyPrint and Liberation Sans). SETTINGS_SPEC 11 has the two new fields.

## [Unreleased] — AI catch-up cron (#135)

- The AI job used to start only when a sync found new mail, so classifications and reply drafts that failed (e.g. before #131) waited for the next incoming message. The new cron `ai_catchup` runs every 15 min. For every mailbox with AI on, it enqueues `process_mailbox_ai_job` (same `_job_id=mail-ai:<id>`, never twice) **only when there is work**: an eligible unclassified message with < 3 attempts, or a reply candidate without a suggestion.
- A reply candidate whose draft failed 3× (`ai_runs` purpose `draft`, status `error`/`invalid_output`) is not retried, so a broken case can't burn the budget every 15 min. Budget and shadow mode are unchanged.

## [Unreleased] — fix: Slovak reply drafts drifted into Czech

- Pilot 2026-10-30: a Slovak reply suggestion mixed in Czech words. The draft prompt said only „Language: sk“; it now names the language in full („Slovak (slovenčina) … never Czech“), and the compose „Napíš za mňa“ task says never to mix Slovak and Czech.
- New warning check `czech_in_slovak` on Slovak drafts (creation and approval): Czech-only letters (ř, ě, ů) or words („jsme“, „děkujeme“, „dotaz“, „zboží“ …) are listed on the card.

## [Unreleased] — reply suggestions also for „Iné“ (#132)

- A reply suggestion is now prepared for every classified message with `needs_reply = true`, in any category, built-in or a 17c custom one. The exception is `NO_REPLY_CATEGORIES` (newsletter, spam, notification, internal, supplier_document). Before, only a fixed list of categories got one, so a customer's „pracujete aj cez víkend? … link na eshop?“ in „Iné“ got none (pilot 2026-10-30). Guards, autonomy (level 2 draft) and the daily budget are unchanged. AI_ASSISTANT §6 documents the rule.

## [Unreleased] — fix: reply drafts failed on claude-sonnet-5-5 (forced tool_choice)

- Pilot 2026-10-30: every reply suggestion and every „Napíš za mňa“ ended with `BadRequestError` — the draft model answers 400 „tool_choice: type "tool" and "any" are not supported for this model“. The Anthropic provider now retries such a call once with `tool_choice: auto` plus an instruction to call the tool, and remembers the model for the rest of the process. Other 400s are still raised, never retried; the API's explanation is logged as `ai.llm_bad_request` (parameter errors only, no mail text). Messages whose draft failed are picked up again on the next AI run.
## [Unreleased] — #127 part 1: back up a folder or the whole mailbox to ZIP

- W2 folder menu „Stiahnuť priečinok (.zip)…“, mailbox menu and Nastavenia › Priečinky „Stiahnuť celú schránku (.zip)…“. The dialog offers Všetky správy / Staršie ako N mesiacov / Od – do, an optional „Vrátane podpriečinkov“, and an estimate (count and size from the synced copy). Then progress, and a download link valid 24 h. The notification „Archív je pripravený“ downloads it too.
- The ARQ job `export_mail_job` reads each message with `BODY.PEEK[]` on a read-only SELECT, so \Seen never changes. Each message goes straight into a ZIP on disk (one FETCH of ≤ 20 messages at a time, never the whole archive in memory) and the file is uploaded to object storage in parts (`storage.put_file`). The download is streamed (`storage.iter_key`).
- ZIP layout: one directory per folder (ASCII slug of the IMAP path), files `RRRR-MM-DD_HHMM_<predmet>_<uid>.eml` with the raw bytes from the server, and `manifest.csv` (folder, UID, Message-ID, date, from, subject, size, sha256, file). stdlib `zipfile` only.
- Job state lives in Redis with a TTL; there is no new table. It holds progress, the storage key, the archive sha256 and the exported UIDs per folder (for part 2, safe delete). One running export per mailbox (409 `export_running`). The hourly cron `delete_expired_exports` removes archives after 24 h.
- Rights: a person with access to the mailbox, not a viewer. A named private folder of somebody else → 403; a whole-mailbox export leaves such folders out. Only the person who started an export sees and downloads it. Audit `mail.export_started` / `mail.export_downloaded` carries folders, range, count, size and sha256, never mail content.

## [Unreleased] — 2f close-out: `make eval` on the server and the category confusion table

- `python -m app.ai.eval_cli sample` picks N random classified messages and writes a label CSV on the server: mode 0600, never inside the repository, no mail bodies. An admin fills `category` (and optionally `language`).
- `make eval` (`eval_cli run`) scores the AI against that CSV: accuracy against the 90 % gate (exit code 1 when missed), precision and recall per category, language accuracy and the confusions. It flags a set smaller than 200. Typos in the labels stop the run instead of counting as errors.
  - Default mode compares the stored classifications and costs nothing.
  - `--live` classifies again with today's prompt and 17c categories. Each call is an `ai_runs` row with purpose `eval` and counts against the daily budget. Stored classifications are never rewritten.
- `--save` stores aggregates only (no ids, no mail text) in `org_settings` (`ai.eval_last`). W12-17f now shows „Presnosť kategórií“: the last result, pass/fail and the confusion table (správne → AI zaradila).
- `tools/eval_label.py` keeps `list-smoke`/`stats` and hands `sample`/`run` to the server CLI.
- **17f label file (Erik's answer B on #129):** „Stiahnuť vzorku na označenie“ gives 200 random messages as an Excel-ready CSV (UTF-8 with BOM, `;`). The column `kategorie_na_vyber` lists „id – názov“ of every category. „Nahrať označenú vzorku“ (≤ 1 MB) accepts the id or the Slovak name (case and diacritics ignored), scores it against the stored classifications and shows the confusion table. Both actions need admin + re-auth and are audited (`ai.eval_sample_downloaded`, `ai.eval_uploaded`). The file is never stored; only aggregates are kept. Errors name the line (e.g. an unknown category).
- The label CSV directory is the named volume `smartmail_eval` (deploy and dev compose), created owned by the app user, so labels survive `update.sh` rebuilds. README shows the server's `dc exec app …` commands; `make eval` is for local dev only.

## [Unreleased] — 2f: 17c categories

- W12-17c „Kategórie“ (admin): one table with Názov, Farba, Zapnutá, Popis pre AI and Počet za 30 dní. Built-in categories keep their ids; you can edit the description and switch them off. Up to 15 custom categories can be added (ids `x_…`). Stored in `org_settings` (`ai.categories`) (#116).
- The classify prompt lists only the enabled categories with the admin's descriptions, and the model may answer only those. An answer with a switched-off category counts as invalid output and falls back like any other.
- Switching a category off removes it from the prompt and the triage list only. Stored classifications keep their category, and its view still opens. „Iné“ is the fallback and stays on.
- Saving is a ⚠ change: password re-auth and audit `ai.categories_changed` with before/after per category.
## [Unreleased] — deterministic web tests (#121)

- vitest: the onboarding tour (W13) opened in whichever W2 test happened to run first, because the „tour seen“ key lived in jsdom's shared localStorage. The G3/G5 confirm-dialog tests then found two dialogs. The test setup now marks the tour as seen before every test, and a tour test removes the key itself. 10 shuffled runs are green.
- Playwright #93/#96: the list removes a row optimistically before the bulk request goes out, so reading the captured requests at once could see `[]`. The tests now wait for the dialog to close and poll the requests (`expect.poll`). No retries were added to CI.

## [Unreleased] — 2f: 17a provider and budget

- W12-17a „Poskytovateľ a rozpočet“ (admin): daily budget, alert %, „Pri vyčerpaní“ and retention are stored in `org_settings` (`ai.limits`). `AI_DAILY_BUDGET_USD` stays the default until an admin saves a budget (1–500 USD, a decimal string); the panel shows „z nastavenia servera“ / „nastavené v aplikácii“, and clearing the field goes back to the server value (#116).
- Saving is a ⚠ change: password re-auth and audit `ai.limits_changed` with before/after.
- All budget checks (pipeline, reply drafts, compose AI, rules preview, usage) read the effective budget.
- „Pri vyčerpaní“: `rules_only` (default) keeps applying 17e rules and leaves other mail for the next day's budget; `ai_off` stops the run as before.
- Provider, region and models are shown read-only from the server environment.

## [Unreleased] — 2f: autonomy per login (W12-07) and 17b overview

- New tables `account_settings` (per login) and `org_settings` (company), migration 0016, reversible, no change to existing tables (#116, Erik's answer A). `org_settings` is used by 17a/17c in the next PRs.
- W12-07 „Samostatnosť“: a matrix of the AI_ASSISTANT §1 actions × levels 0–4, set by each login for all its persons (D8). Changing it is a ⚠ change: password re-auth and audit `ai.autonomy_changed` with before/after.
- Hard rule in code (`app/ai/autonomy.py`): external send and Money writes never go above level 2. Values are clamped when saved and when read, so a stored 3/4 is ignored. Those rows show a lock and levels 3–4 are disabled.
- W12-17b „Samostatnosť AI“ (admin): read-only overview per active login, no admin maximum.
- Levels are stored and shown; the pipeline starts reading them as each action lands (today only reply suggestions exist, at level 2).

## [Unreleased] — Konverzácie: opening marks the whole conversation read

- In Konverzácie mode, opening a conversation marked only its newest message read, so the thread was bold again after a refresh (pilot, Nitra). The web now sends `mark_thread=true` in this mode, and `GET …/messages/{id}` marks every unread message of the thread in that mailbox (one IMAP `\Seen` per folder, audit `mail.thread_seen`). The row and folder counts update at once. List mode still marks only the opened message, as in Roundcube.

## [Unreleased] — inline image preview in compose

- W4: a pasted screenshot or a toolbar image showed as a broken image in the editor, because the body keeps `src="cid:…"` for the sent mail and a browser can't load `cid:`. The editor now shows the draft's own copy from the new `GET /api/mail/compose/{draft}/inline/{content_id}` (own drafts, inline png/jpeg/gif only, never an infected file, `nosniff`). The saved and sent HTML still says `cid:`, so the recipient gets the related MIME part as before.

## [Unreleased] — paste screenshots into compose

- W4: Ctrl+V of an image (a Win+Shift+S / PrintScreen screenshot, a copied picture) inserts it as an inline image at the cursor, like Roundcube (PRODUCT_SPEC §1 „paste images“, SCREENS_SPEC W4). It uses the same upload as the toolbar image button (ClamAV, CID at send). Text and HTML pastes are unchanged. Screenshots get the name `snimka-<time>.png`.

## [Unreleased] — external links open in a new tab

- Reading pane: an http(s) link in a received mail opens in a new tab (`noopener,noreferrer`), so Smart Mail stays open. This works for messages already stored too, because it is handled on click, not in the stored HTML. mailto: and in-page anchors are unchanged.

## [Unreleased] — Phase 2f PR 2: W12-17f shadow mode, consumption and accuracy

**Settings 17 › „Tieňový režim, spotreba a presnosť“** (admin):
- **Shadow switch** for AI reply suggestions:
  - it reads and writes the existing `ai_shadow_mode` flag; the default stays **on**;
  - turning it off needs a confirm („Zobraziť AI návrhy odpovedí všetkým?“);
  - audit `ai.shadow_mode_changed` (before/after).
- **Read-only numbers, last 30 days:**
  - cost per day (bars) and per purpose vs the daily budget;
  - reply suggestions: created / in shadow / approved / approved without edits % / rejected;
  - top reject reasons and the category distribution.
- CSV export of the daily cost.
- No mail text in the API.

The switch is code only. Turning shadow off on the test server stays Erik's decision; no rows were changed.

## [Unreleased] — Phase 2f PR 1: injection suite + fact-check fix

**Injection suite** (AI_ASSISTANT §12; `make injection`, also part of `pytest`):
- 22 fictional malicious fixtures in `fixtures/ai/injection/cases.json`, covering classify, reply, compose, rules, knowledge cards, style samples and approve.
- In each case the scripted model **obeys** the attack, and the test proves the code still holds:
  - wrappers stay closed;
  - unknown categories and priorities are refused;
  - the recipient never comes from the model;
  - invented numbers and placeholders block, security notes warn;
  - rules can't forward or delete;
  - approve only prepares a draft.

**Fix found by the suite:** the number/fact check ignored numbers with a letter prefix. A **made-up IBAN** (`SK99…`) or invoice number (`FV2026/0999`) in a draft was not flagged. Now:
- they block unless they appear in the thread or knowledge;
- an IBAN written in groups still matches the thread;
- sizes like M8 / M10 still pass (fewer than 3 digits).

## [Unreleased] — Phase 2e PR 5: personal style profile (Settings 07)

**„Môj štýl písania“ in W12-07:**
- opt-in per person;
- „Vytvoriť / Aktualizovať profil“ builds it from the person's own last 200 sent e-mails (their text only — no quoted mail, no signature; at least 5);
- the profile is editable;
- switching off **deletes** it.
- Stored in `user_settings` › `ai.style_profile` (#110, no table).

**Profile content:** max 12 Slovak bullet points about how the person writes; the model is told never to include names, addresses, phone numbers, prices or document numbers.

**Use:** the compose AI panel (2d) adds the writer's profile to the company style guide for that person's drafts.

**Guards:**
- AI availability and the budget are checked; `ai_runs` row;
- audit `ai.style_profile_updated` / `_generated` without the profile text.

This completes milestone **2e**.

## [Unreleased] — Phase 2e PR 4: W12-17e Pravidlá

**Settings 17 „AI – správa“ › „Pravidlá“** (admin), with the settings schema regenerated.

**Creating a rule:**
1. Write the rule in Slovak.
2. **Previesť** shows the „Ak … tak …“ form generated by the server.
3. Optionally **Vyskúšať na posledných 50 e-mailoch**, which shows the count and up to 10 matches.
4. **Uložiť pravidlo** saves it; nothing is saved before this step.

If the AI can't express the rule (e.g. „pošli ďalej“), a hint is shown and there is nothing to save.

**List:** Pravidlo, Prevedená podoba, an on/off switch, Autor, Posledné použitie, and delete with a confirm.

## [Unreleased] — Phase 2e PR 3: 17e rules in natural language (backend)

**`StructuredRule`** (`app/ai/user_rules.py`):
- 1–5 conditions (from_email / from_domain / subject / body / attachment_name / has_attachment; contains / equals / ends_with; all / any);
- 1–3 **internal** actions only: set_category, set_priority, needs_reply / no_reply. No send, move, delete or Money.
- The „Ak … tak …“ sentence is generated by **code** from the structure.

**API** (admin, 17e):
- `POST /api/settings/ai/rules/preview` (LLM → structure, saves nothing; anything outside the allowed actions → 422 `rule_not_understood`);
- `POST /api/settings/ai/rules` saves the confirmed structure;
- list, enable/disable, delete;
- `POST /api/settings/ai/rules/test` tries the rule on the last 50 e-mails and changes nothing.
- Audit `ai.rule_created` / `_updated` / `_deleted`.

**Execution:** deterministic in the AI pipeline before classify.
- A rule with a category decides **without an LLM call** (`source: user_rule`, security notes still computed).
- Priority and reply flags override the classifier.
- `no_reply` means no reply suggestion.
- `last_used_at` is updated; disabled or invalid rules are skipped.

## [Unreleased] — Phase 2e PR 2: W12-17d Štýl a znalosti

**Section 17 „AI – správa“** (admin) in Settings, with tab 17d „Štýl a znalosti“. The settings schema and its JSON snapshot are regenerated.

**On the page:**
- **Štýlová príručka firmy:** one text field + Uložiť.
- **Znalosti:**
  - a table of cards (Názov, Platné do with an „neplatná“ hint, Tagy, Zapnuté) with edit and delete (confirm);
  - „Pridať kartu“ opens a form: Názov, Text, Platné do, Tagy (comma-separated), Zapnuté.
- Non-admins see the admin-only notice.

**Fix:** card text can no longer close its `<company_knowledge>` block or open an `<untrusted_email>` block in the prompt (#111 review).

## [Unreleased] — Phase 2e PR 1: knowledge cards, style guide, full-text retrieval

**Migration 0015** (#110, Erik A; reversible, no change to existing tables):
- `knowledge_cards`: `kind` knowledge | style_guide, with the style guide as one row (partial unique index); title, body, valid_until, tags, enabled, created_by; a full-text `search_vector` trigger (simple + unaccent).
- `ai_rules`: used in a later 2e PR.

**Retrieval** (`app/ai/retrieval.py`, ADR-014):
- `Retriever` protocol with `FullTextRetriever`: up to 3 enabled, valid cards matching the mail's words.
- Letters-only OR query, so no tsquery syntax gets through.
- Embeddings can replace it in this one module later.

**Prompts:**
- Reply drafts (2c) and the compose panel (2d) get the company style guide (system prompt) and the matching cards.
- Cards go in `<company_knowledge>` blocks marked as data, not instructions.
- Numbers from those cards count as facts for the number check, at creation and at approve (`knowledge_ids` in the payload).

**API** `/api/settings/ai/style-guide` (GET/PUT) and `/api/settings/ai/knowledge` (list / create / edit / delete):
- admin only (17d);
- audit without card text.

**Docs:** ADR-014; CLAUDE.md §4 data model updated; `docs/plans/phase-2.md`.

The W12-17d UI follows in the next PR.

## [Unreleased] — Phase 2d PR 3: live „Kontrola pred odoslaním“ + send-gate fixes

**Live checklist** in the W4a panel / M17 sheet:
- built from the draft's server checks, recomputed on every autosave;
- problems first, then green rows for the four W4a items: bez [[DOPLNIŤ]], príjemcovia z jednej firmy, príloha, jazyk sedí so zákazníkom.

**New checks:**
- `multiple_companies` (warning): external recipients from more than one domain.
- `language_mismatch` (warning): the person's text vs the customer's language.
  - Classification or detection is used for the customer's language.
  - Slovak ↔ Czech counts as compatible; short texts aren't judged.

**Fixes:**
- The placeholder check matched only the bare `[[DOPLNIŤ]]`. Now **every form**, e.g. `[[DOPLNIŤ: cena]]` as the AI writes it, blocks sending.
- **Blocking checks can no longer be forced** through the send API; „Odoslať aj tak“ is only for warnings (W4b).
- The attachment warning counts only the person's own text (not the quote or the signature), and not when a file is attached.

## [Unreleased] — Phase 2d PR 2: W4a compose AI panel + M17 sheet

**Panel:**
- W4 right panel gets the tabs „Možnosti a prílohy | ✦ AI“, plus a ✦ AI toolbar button.
- On the phone, the button opens the M17 bottom sheet.
- Shown only where AI runs for the mailbox (`ai_available`), and not in Klasické zobrazenie.

**Contents:**
- „Napíš za mňa“;
- chips Kratšie / Formálnejšie / Priateľskejšie / Opraviť gramatiku / Doplniť odpoveď na všetky otázky;
- „Preložiť do“ (sk/cs/en/de/pl/hu).

**Result:**
- Every result is a **word diff** of the person's own text, with „Použiť“ / „Zahodiť“.
- „Použiť“ replaces only the text before the quote and the signature; those blocks are never sent to the model nor replaced.
- Unanswered questions and `[[DOPLNIŤ]]` placeholders are listed.
- Read-only: disabled.

**API:** the endpoint moved to `/api/mail/compose/{draft_id}/ai`, next to the rest of the compose API.

## [Unreleased] — Phase 2d PR 1: compose AI endpoint (W4a / M17 backend)

**`POST /api/compose/{draft_id}/ai`** handles these actions:
- `write` (Napíš za mňa, with an instruction);
- `shorter` / `formal` / `friendly` / `grammar`;
- `translate` (sk/cs/en/de/pl/hu);
- `answer_all` (Doplniť odpoveď na všetky otázky, returns the unanswered questions).

**What the model gets and returns:**
- Only the person's own text, plus the quoted thread of a reply wrapped as untrusted.
- **Never the signature:** the signature and the quote are added by the program.
- Returns a proposal only: nothing is saved or sent; the editor shows it as a diff („Použiť“ / „Zahodiť“).
- `[[DOPLNIŤ…]]` placeholders are reported.

**Guards:**
- Needs an active person, AI enabled on the mailbox, and `LLM_MODEL_DRAFT` + key; otherwise 409 `ai_unavailable`.
- The daily budget applies (429 `ai_budget_exceeded`).
- Every call is an `ai_runs` row.
- Audit `ai.compose_assist` (action and status, no text).

## [Unreleased] — #94 Phase 2c PR 3: AiSuggestionCard in the reading pane

**Card** (`features/ai/AiSuggestionCard.tsx`, UX_SPEC §3.1, type `reply`):
- In W2c below the security banner: at most 2 cards, plus „Ďalšie návrhy (n)“.
- Header: ✦ „Návrh odpovede“, with the category and language as a subline.
- `CheckRow`s: blocking, then warnings, then the green rows; up to 4 shown, plus „Ďalšie kontroly (n)“.
- Draft preview, clamped with „Zobraziť celý text“, and the „Prečo“ rationale.
- State border: ready green, attention amber, blocked red, low confidence grey with „AI si nie je istá“.
- Footer: „Návrh AI – nič sa neodošle ani nezapíše bez vášho schválenia.“

**Actions:**
- **Pripraviť koncept** → approve (#105) and open the draft in W4. Nothing is sent from the card.
- **Upraviť** edits the text inline; the approve then sends the edited text. A blocked card becomes approvable after an edit, since the server re-checks.
- **Zamietnuť** → reason chips (zlá kategória / nesprávne údaje / tón / netreba) plus an optional note.
- Read-only: all actions disabled.
- Klasické zobrazenie hides the cards. Shadow-mode suggestions never reach the client.

## [Unreleased] — #94 Phase 2c PR 2: approve / reject reply suggestions (backend)

**`POST /api/suggestions/{id}/approve`** (optional edited `body`). Needs an active person (viewer → 403). Order of work:
1. Locks the row.
2. Re-runs the reply guards on the final text: blocking → 409 `suggestion_blocked` with the checks, nothing changes.
3. Creates a **reply draft** through the normal compose code. The AI text is escaped into paragraphs above the quote, and the signature of the person who approves is added.
4. Saves it to **Koncepty** (IMAP APPEND).

**Approve never sends** (autonomy level 2, hard rule). It also stores who decided and when, the final payload with `draft_id`, and the diff when edited.

**`POST /api/suggestions/{id}/reject`** stores the reason chips `wrong_category` / `wrong_data` / `tone` / `not_needed` (AI_ASSISTANT §10) and an optional note.

**Both endpoints:**
- shadow rows and other mailboxes → 404;
- a second decision → 409 `suggestion_decided`;
- audit `ai.suggestion_approved` / `ai.suggestion_rejected` (actor user, no body).

The card UI follows in PR 3.

## [Unreleased] — #100 classify prompt with category descriptions

**Problem:** a supplier's own invoice was triaged as „Žiadosť o faktúru“.

**System prompt** (`classify_system`) is now built from `CATEGORIES`:
- every category's id, Slovak name and description (SETTINGS_SPEC 17c; in 2f, 17c swaps only the source list);
- direction rules for the pairs the model confuses:
  - `supplier_document` (issued TO us) vs `invoice_request` (someone ASKS us);
  - `payment`;
  - `inquiry` vs `order`;
  - `supplier_info` vs `newsletter`.

**User prompt:**
- now has a `Recipients:` line: the count, our own addresses, and external ones only counted;
- attachment names keep their extensions;
- untrusted wrapping is unchanged.

There is no rule from „Faktura“ in the subject; the ISDOC/UBL rule already existed.

**Eval:** fictional smoke fixtures 004–006 (supplier invoice PDF+CSV, invoice request, payment reminder), with a test that every smoke fixture is fictional and valid.

## [Unreleased] — #96 PR 2: drag & drop onto folders

- Desktop: drag a message row onto a folder in the G3 column to move it.
- If the dragged row is selected, the whole selection moves.
- Folders show the Figma drop-target highlight while dragging; the dragged row is dimmed.
- The folder the messages are in is not a drop target.
- A drop uses the same optimistic `move` as Presunúť do… (#89). Read-only: rows are not draggable.

## [Unreleased] — #96 PR 1: Presunúť do… / Kopírovať do…

- New bulk action `copy` (IMAP UID COPY):
  - the source is untouched, and the destination count rises at once;
  - the destination gets the copies on the scheduled sync;
  - audit `mail.bulk_copy`.
- `move`/`copy` into the folder the message is already in is a no-op.
- Folder picker (`FolderPicker`, Roundcube order: special folders, Archív, then customer folders alphabetically; the current folder is disabled; on a phone it docks at the bottom like a sheet). It is used by:
  - Viac › Presunúť do… / Kopírovať do… in the reading pane;
  - Presunúť in the W2e bulk bar;
  - shortcut `L` (shown in W15 again).
- Move goes through the optimistic path (#89). Read-only (no active person): disabled.
- Menus scroll when longer than the window.
- Drag & drop onto a folder follows in PR 2.

## [Unreleased] — #94 Phase 2c PR 1: reply suggestions (backend)

### Fixed
- Mobile: opening a message from AI triedenie showed a blank screen when the message lives outside Doručená pošta (e.g. Sieve files supplier invoices into Faktúry). The message now opens in its own folder, and `?m=` names it so the pane loads it even when it is not on that folder's current page.

**Reply step** (`app/ai/reply.py`):
- Runs after classify in `process_mailbox_ai_job`, for a message that:
  - is classified `done` with `needs_reply`;
  - is in a reply category (inquiry, order*, invoice_request, complaint, shipping, payment, document_request);
  - is in an AI-eligible folder and arrived after `ai_enabled_at`;
  - is not from our own mailbox.
- The step gets one `reply` suggestion (draft model `LLM_MODEL_DRAFT`, `propose_reply` tool, no Money tools):
  - the body is fetched from IMAP only for these messages;
  - the last 5 thread messages go to the model, wrapped as `<untrusted_email>`;
  - prompts are `app/ai/prompts/system_base.md` and `draft.md`.
- Once per message and per Message-ID across copies.
- The daily budget applies: a paid call is always an `ai_runs` row with purpose `draft`.
- Errors or invalid output leave no row, so the next run retries.
- The `ai_shadow_mode` flag sets `shadow`. It is **on by default**: without a flag row, suggestions stay hidden.
- Audit: `ai.suggestion_created` (actor ai, no body).

**Guards** (`app/ai/guards.py`, AI_ASSISTANT §9 without Money):
- blocking:
  - `[[DOPLNIŤ…]]` placeholder;
  - empty body;
  - a number/date in the draft that is not in the thread (fact check);
  - missing recipient.
- warnings:
  - new recipient outside INTERNAL_DOMAINS;
  - security notes from classification (DMARC/SPF fail, display-name spoof, IBAN change);
  - „v prílohe“ without an attachment;
  - language mismatch.
- The recipient always comes from the message, never from the model.

**Endpoint:**
- `GET /api/mail/mailboxes/{ref}/messages/{id}/suggestions` returns the pending, non-shadow suggestions of a message and its copies **in the same mailbox**, with checks and `blocked`.
- The card UI and approve/reject follow in the next PRs.

**Docs:** `docs/plans/phase-2.md` records Erik's decisions of 29 Oct (budget 5 USD, eshop@ first, shadow week, model ids).

## [Unreleased] — #93 list keyboard shortcuts (UX_SPEC §6)

**Central handler:**
- One handler: `features/system/shortcuts.ts` (matcher + registry) and `useGlobalShortcuts` (the only keydown listener).
- The mail screen registers what each key does.
- Never while typing (inputs, contenteditable/TipTap) or while a modal is open.
- Read-only (no active person) ignores the action keys.
- Settings 01e „Klávesové skratky zapnuté“ is now a real switch (`prefs.shortcuts.shortcuts_enabled`); `GET /api/mail/prefs` returns `shortcuts.enabled`.

**New keys:**
- ↑/↓ open the previous/next message (and scroll it into view).
- Enter opens the message.
- **Delete** = Vymazať (same optimistic path as the toolbar, #89).
- **Shift+Delete** = Vymazať natrvalo after a confirm dialog: new bulk action `purge` (`\Deleted` + UID EXPUNGE in place, no copy in Kôš).
- Ctrl+A selects every row on the page.
- U = neprečítané, ! = nevyžiadané.
- R / Shift+R / F = odpovedať / všetkým / poslať ďalej.
- Compose: Ctrl+Enter = Odoslať (same click as the button, so the pre-send checks still run).

**W15 help dialog:**
- E, #, L and [ are hidden until their features exist: vybavené and priradiť come in Phase 5; there is no folder picker and no collapsible folder column yet.

## [Unreleased] — #89 fast delete / move / flags (no sync inside the request)

### Fixed
- Deploy: `deploy/docker-compose.yml` did not pass the AI settings (`ANTHROPIC_API_KEY`, `LLM_PROVIDER`, `LLM_MODEL_*`, `AI_DAILY_BUDGET_USD`) from `.env` into the app and worker containers, so the key set by install.sh never reached the app. `tests/test_deploy_env_passthrough.py` now fails when install.sh writes an app setting that compose does not pass.

**Backend:**
- Toolbar actions (bulk `delete`/`junk`/`archive`/`move`, delete inside Kôš = expunge, flags, the read mark when a message is opened) now handle the request in this order:
  1. run the IMAP command;
  2. apply the same change locally in the same request (`app/mail/local_apply.py`):
     - removed rows are deleted from the source folder;
     - flags and the `seen`/`flagged` columns are set;
     - folder `total`/`unread` and the thread counts are updated;
  3. commit.
- A full `sync_mailbox` no longer runs inside the request.
- Moving actions **schedule** a sync instead (`app/mail/sync_schedule.py`):
  - an ARQ `sync_mailbox_job`, 3 s deferred, with the poll's job id;
  - quick actions in a row give one sync;
  - flag actions schedule nothing.
- New log line `mail.action_done` with `action`, `n`, `imap_ms` and `ms`. It contains no message data.

**Web (optimistic UI, `features/mail/optimistic.ts`):**
- On delete/junk/archive/move, the rows and folder counts change at once and the reading pane closes.
- Flags change the row icon at once.
- A failed request rolls back with the error toast.
- The list is invalidated after the request settles instead of being refetched right away.

## [Unreleased] — #85 react-router 6 for the pilot (ADR-013)

### Fixed
- „Kto ste?“ (W1b/M0), the PersonChip and Viac (M18) show the person's uploaded photo instead of the initials (UX_SPEC W1b: photo or initials). `PersonOut.photo_url` is added; `Avatar` takes an optional `photoUrl`.

- Decision (Erik, B): stay on react-router 6.x; upgrade to 7.x in Phase 7. Recorded in `docs/adr/013-react-router-6-pilot.md`, including the advisory IDs.
- `safeInternalPath` guards every navigation target taken from router state or server data:
  - accepts only paths that start with `/`;
  - rejects `//`, any backslash and control characters;
  - used by `returnTo` (W1, W1a, W1b), W16, W17 and notification links.
- Regression test: `#85 safeInternalPath`.

## [Unreleased] — #81 Phase 1 close-out

### Fixed
- Person photo, branch logo and signature image uploads failed on the server (500 / „nepodporovaný formát“): Pillow was a dev-only dependency and the Docker image installs `--no-dev`. Pillow is now a runtime dependency; `tests/test_runtime_dependencies.py` fails when `app/` imports a dev-only package.

**Done in Phase 1:**
- mailbox login (IMAP) with 2FA for personal accounts and re-auth for admin changes;
- branches, persons, „Kto ste?“ and branch signatures;
- folders and sync, list, reading pane, compose (drafts, undo send);
- search and contacts;
- Settings 01–06, 09, 10–12; Filtre and Mimo kancelárie via ManageSieve;
- system screens W13–W17;
- installable PWA and mobile;
- Klasické zobrazenie;
- Roundcube import tool.

**Not done / deliberately different:**
- 2FA and OIDC are hidden in W12-10;
- „Vymazať účet“ is omitted;
- the 11d unhandled-mail alert is deferred to Phase 5;
- the permission matrix follows PRODUCT_SPEC.

**Open risks:**
- ManageSieve availability at nameserver.sk;
- the per-country SMTP block for new mailboxes (enable DE);
- the acceptance days have not run yet (eshop@ full day, Nitra branch day);
- `APP_ENV=prod` on the test server;
- avatar initials contrast (#83);
- react-router 6 moderate advisories (#85).

**This PR:**
- Review package `docs/phase1-review.md` (35 screen IDs, desktop and mobile screenshots, Figma links, gate results). The Figma MCP was unreachable (proxy 403) in this run.
- `web/e2e/phase1-review.spec.ts`: a screenshot and an axe check (wcag2a/aa, no serious or critical findings) for every listed screen, on desktop and mobile.
- Trivial a11y fixes:
  - darker text tokens for the status page caption, the message date and the notification group heading;
  - a label on the filter name input;
  - focusable scroll regions in W12-10.
- Lighthouse 11.7.1 on the production build: installable, PWA 100.

## [Unreleased] — #77 PR 2: enforce „Vyžadovať 2FA“, admin reset

### Fixed
- Uploads over 1 MB (a person photo, compose attachments up to 25 MB) failed with nginx's default 413: `/api/` now allows `client_max_body_size 26m` in every nginx config (dev, VPS, tunnel). `update.sh` reloads nginx on deploy (#61).

### Fixed
- Settings 11: the last active person of a branch **without a branch login** can be deactivated or deleted, so an unused (test) branch can be emptied and removed with „Vymazať pobočku“. A branch with a login still keeps one active person for „Kto ste?“.

- Login of a personal account with `require_2fa` and no TOTP → `next: "2fa-setup"`: an `mfa_pending` session plus a
  Redis flag (`smartmail:mfa-setup:<session>`, 10 min; B1, no schema change). It reaches only `me` and the 2FA setup
  (`/api/settings/security/2fa`, `…/start`, `…/confirm`); everything else answers 403 `mfa_setup_required`; logout
  works. The typed password counts as the re-auth for `start`. After `confirm` the session becomes a normal one.
  The flag is removed on logout and, after the commit, for revoked sessions (as the re-auth of #54).
- W1a setup mode (`/login/2fa?setup=1`): „Nastavte dvojstupňové overenie“ with the Settings 09 dialog; a 403
  `mfa_setup_required` anywhere routes there.
- W12-10 (personal accounts only, C1): „Vyžadovať 2FA“ switch (PATCH `require_2fa`, re-auth, audit before/after
  incl. `require_2fa` / `totp_enabled`; branch login → 422 `personal_only`) and „Resetovať 2FA“
  (`POST /api/settings/admin/users/{id}/reset-2fa`, re-auth, confirm): removes TOTP and backup codes and signs the
  login out everywhere. Nothing is switched on automatically (D1).

## [Unreleased] — #77 PR 1: turn two-factor authentication on / off (Settings 09)

- New dependency (approved on #77, A1): `qrcode.react` **4.2.0** (exact pin, ISC licence) — renders the QR code in
  the browser.
- `GET /api/settings/security/2fa`, `POST …/start` (new secret + 10 backup codes, shown once; until confirmed kept in
  Redis for 15 min — secret Fernet-encrypted, codes as hashes; a new `start` replaces an unconfirmed one),
  `POST …/confirm {code}` (±1 time step, the confirming step cannot be reused at login, 5 wrong codes end the setup),
  `POST …/disable` (re-auth of this session and person; 409 `totp_required` while an admin requires 2FA).
  `start` needs the same re-auth and the pending setup is bound to the session that started it (#79 review).
  Personal accounts only (403 `personal_only`). Audit `auth.totp_enabled` / `auth.totp_disabled` without secrets.
- W12-09 Bezpečnosť: „Dvojstupňové overenie“ row (vypnuté / zapnuté, Zapnúť / Vypnúť) and the dialog of Figma
  `67:58896` (QR, key by hand + Kopírovať, code from the app, 10 backup codes + Stiahnuť kódy).
- The re-auth dialog now renders after the router, so it stacks above a confirm dialog that triggered it.
- Enforcement („Vyžadovať 2FA“, admin reset) follows in PR 2.

## [Unreleased] — #54 re-auth (password) for ⚠ admin changes

- `POST /api/auth/reauth {password}`: the mailbox password of the signed-in login, checked on the mail server like
  the login; counts towards the login rate limit; a wrong password answers 422 `reauth_failed` and never logs out;
  audit `auth.reauth` (ok / failed, never the password).
- Re-auth time in Redis per session (`smartmail:reauth:<session_id>`, TTL 15 min, value = account) — no schema
  change (Erik's answer on #54). Removed on logout and, after the commit, for revoked sessions (Odhlásiť zo všetkých
  zariadení, conversion to a branch login, password change), so a rolled-back change keeps the session's re-auth.
- `RecentReauth` (admin + re-auth of *this* session, else 403 `admin_required` / 401 `reauth_required`) on: users
  create / PATCH / Overiť / Odhlásiť zo všetkých zariadení / Prístup k schránkam, link-login, delete branch, delete
  person, mailbox server settings; person PUT only when Rola or Aktívna changes.
- Web: „Potvrďte heslom“ dialog for `reauth_required` that repeats the original request (several requests share one
  prompt); cancel = no change, never a logout. 2FA enforcement is a separate issue.

## [Unreleased] — #55 part 2: Settings 10 Používatelia a role to Figma (W12-10)

- Layout: the accounts are a full-height column with „Hľadať účet“; the list shows Typ · Rola or „N osoby“ of a branch
  login (`persons_count`) · last login; „Vytvoriť“ sits in the header; Uložiť / Zrušiť bar with „Neuložené zmeny“.
- „Overiť“: `POST /api/settings/admin/users/{id}/verify` — one test login on the mail server with a password typed by
  the admin; never stored or logged; failures count towards the login rate limit; audit `settings.user_verified`.
- „Odhlásiť zo všetkých zariadení“: `POST /api/settings/admin/users/{id}/logout-all` (confirm; revoke reason
  `admin_logout`; audit with the number of sessions).
- „Prístup k schránkam“: `GET/PUT /api/settings/admin/users/{id}/mailbox-access` — Čítať / Odosielať ako per mailbox
  (Odosielať needs Čítať; the login's own mailbox is fixed); audit before/after.
- „Matica oprávnení“ (read-only) from PRODUCT_SPEC §4.
- Not shown (customer decision): „Vyžadovať 2FA“, „Prihlásenie cez Microsoft/Google“, „Vymazať“ account.

## [Unreleased] — #55 Settings 11 Pobočky a osoby to Figma (W12-11a/b/d)

- Layout: the branch list is its own full-height column with „Pridať pobočku“ at the bottom; the branch name is the
  page title; breadcrumb … › Pobočka › tab; „Vymazať pobočku“ top right; tabs with the people count on „Osoby“.
- 11b Osoby: the whole row opens the drawer (click, Enter) plus a pencil „Upraviť osobu {meno}“ (pilot finding);
  „Aktívna“ is a switch in the row (409 `last_active_person` keeps ≥ 1 active person); photos in the table.
- Drawer: „Fotka“ (`POST/DELETE /api/settings/admin/people/{id}/photo`, JPG/PNG ≤ 5 MB, centred square 256 px →
  {fotka}); „Pôsobí aj na pobočkách“ (`cover_branch_ids`, person_branches, audited). „Obchodník v Money“ stays hidden
  until Phase 3.
- 11a Údaje: „Logo do podpisu“ (`POST/DELETE /api/settings/admin/branches/{id}/logo`, PNG/SVG→PNG ≤ 200 kB →
  {logo} in preview and as CID at send), „Priečinky pobočky“ (`GET /api/settings/admin/branch-folders`, D21), and the
  Uložiť / Zrušiť bar.
- 11d Prihlasovanie: „Opýtať sa Kto ste? po nečinnosti“ and „Zostať prihlásený na zariadení“. „Prehľad pobočky –
  upozorniť na nevybavené“ is left for Phase 5 (no column yet, customer decision).
- „Vymazať pobočku“ (`DELETE /api/settings/admin/branches/{id}`): only an empty branch — 409 `branch_has_people` /
  `branch_has_login`; inactive persons keep their name and lose the branch; audit `settings.branch_deleted`.
- Settings 10 (Používatelia a role) parity follows in a separate PR.

## [Unreleased] — Pilot #71: person of a personal login (eshop@) in Pobočky a osoby

- W12-11b Osoby: section „Osobné účty“ (persons of personal logins, `GET /api/settings/admin/personal-people`) with
  the same drawer; field „Pobočka (pre podpis)“ (select of branches + „bez pobočky“), no manager flag, no delete.
- `PUT /api/settings/admin/people/{id}` accepts `branch_id` (omitted = unchanged, null = no branch) only for the person
  of a personal login (422 `branch_only_for_personal_account`); audit before/after includes `branch_id`.
- „Kto ste?“ of a branch login, the branch people list, the last-admin guard and the last-active-person rule leave out
  persons with an own personal login, so the signature branch never puts them into a branch picker.
- Signature: on a mailbox other than the branch's own, the identity's own signature wins and the branch only fills
  {pobocka}, {adresa_pobocky}, {telefon_pobocky}; on the branch mailbox the branch template still rules.
- „Zmeniť na prihlásenie pobočky“ deactivates the placeholder person also when it had a signature branch.

## [Unreleased] — Pilot #69: SMTP server reply on a refused send

- `send_message`: an SMTP refusal keeps the server's reply in `SmtpError.reason` / `send_error`
  (`SMTPSenderRefused:550:Sending mail from your country (de) is not allowed` — one line, max 200 characters, only
  the server's text, never the message). Log `smtp.send_failed` carries `smtp_code` + `smtp_message`.
- W4/M4 send error banner: „Odpoveď servera: …“ under the Slovak message; for 550 with „country“ the hint to allow
  sending from abroad in the mailbox administration.

## [Unreleased] — Pilot #68: sender of a branch identity (nitra@ vs smartsronitra@)

- Nastavenia › Identity on a branch login: section „Identita“ (Zobrazované meno, E-mail, Organizácia, Odpovedať na)
  above the branch signature preview, as in Figma W12-03a. An admin edits it, everybody else sees it read-only. The
  signature stays the branch template.
- `PUT /api/settings/identities/{id}` on a branch mailbox: admin only (403 `admin_required`); sender and reply-to must
  be company addresses (`INTERNAL_DOMAINS`, 422 `identity_email_not_internal`); the branch identity's signature HTML is
  not touched. Audit `settings.identity_saved` with before/after (names and addresses, never the signature).
- `signature-context`: `{email_pobocky}` in the preview is the default identity's e-mail, as in compose.
## [Unreleased] — Pilot #52: paperclip before the first open (BODYSTRUCTURE)

- The envelope sync also fetches `BODYSTRUCTURE`; `has_attachments` is set at insert, so unopened messages show the
  paperclip and „S prílohou“ finds them (Roundcube parity). Rule as #51 / B9: an attachment disposition, a forwarded
  `.eml`, or a named non-body part counts; `multipart/related` images with a Content-ID and inline images do not;
  unknown or broken structures → no paperclip. `ensure_body` stays authoritative on the first open.
- One-off backfill for mailboxes synced before: worker job `backfill_attachment_flags` (minute 5 and 35, one mailbox
  per run) fetches `BODYSTRUCTURE` of unopened messages in batches of 500 with a pause, under the mailbox sync lock;
  a Redis marker makes it run once per mailbox. No schema change. One run holds the sync lock at most 120 s (budget
  checked before each batch); an interrupted run stores the last checked UID per folder and the next run continues;
  the marker is set only when every folder is done.
- After the first open the list row gets the paperclip from the detail at once (`applyAttachmentFlagLocally`), no F5.

## [Unreleased] — Pilot #65: signature person in compose („Odpovedá: … ▾“)

- W4/M4: own row „Odpovedá“ with a chip of the **draft's** signature person (`signature_person_name`), never just the
  active person. On a branch login it is a dropdown with the persons of „Kto ste?“; choosing one swaps only the
  signature block (typed text and quote stay).
- After a person switch with a draft open: warning „Podpis: {draft} – zmeniť na {active}?“ [Zmeniť] [Ponechať]; the
  signature never changes silently.
- `PATCH /compose/{id}`: `signature_person_id` must be eligible for the login (else 422
  `signature_person_not_allowed`); an edited one-off signature needs `replace_signature_override` (else 409
  `signature_override_confirm`, UI „Prepísať upravený podpis?“); audit `mail.compose_signature_person` with
  before/after. Send keeps `signature_person_id or person_id`.
## [Unreleased] — #62: flaky W12-11a e2e (red main)

- Cause: since #53 the W12-11a Údaje tab loads `GET /api/settings/admin/mailboxes`; `phase1-visual.spec.ts` did not mock
  it, the e2e mock answered 401 and the global handler sent the page to /login — sometimes before the breadcrumb
  assertion. Test-only; the app behaves correctly (a real 401 must sign out).
- `e2e/fixtures.ts`: Settings 10/11 admin endpoints in `SETTINGS_DEFAULTS`; every unmocked API call is logged as
  `[mockApi] unmocked … → 401`. The two other unmocked calls of the suite (settings preferences in the axe test,
  image proxy) are mocked; the full suite now has none.
## [Unreleased] — Pilot #38: body search also on the IMAP server (Roundcube parity)

- `GET /api/search?server=true`: for Telo (`BODY`) and Celá správa (`TEXT`) the backend also runs `UID SEARCH CHARSET
  UTF-8` on the IMAP server for the folders in scope and merges the UIDs with the local hits, so text in the body of
  messages that were never opened is found (ADR-012). Terms are reduced to safe characters (no IMAP injection), 15 s
  timeout, `server_search: ok|partial|timeout|unavailable|busy`; the local hits are always returned. At most one
  server search per mailbox at a time (Redis lock; a second one answers `busy`), and the IMAP socket timeout plus a
  per-folder deadline end the session soon after a timeout.
- W10/M8: local results first, then „Hľadá sa aj na serveri…“ and the merged result; a timeout or an unreachable
  server is explained. Subject / sender fields never ask the server.

## [Unreleased] — Pilot #46: W2l attachment preview (PDF, images, ISDOC/XML)

- Clicking a PDF, raster image (not SVG) or XML/ISDOC attachment opens W2l, a full-screen dark lightbox, instead of
  downloading. Other types download as before. Infected files never open; „not scanned“ asks first, as before.
- PDF via `pdfjs-dist` 4.10.38 (lazy-loaded, worker bundled by Vite, same origin, `isEvalSupported: false`, no
  `<embed>`/`<iframe>`): canvas + selectable text layer, „Strana 1 / 2“, previous/next page (PageUp/PageDown),
  zoom ±, the whole page in the window on desktop, fit width on phones. Images: zoom, rotate. XML/ISDOC: table of
  leaf values. Toolbar: Stiahnuť, Tlačiť (prints the rendered pages, never the PDF), ←/→ and swipe between
  attachments, Esc closes. „Pripraviť dodací list prijatý“ / „Importovať…“ stay hidden until Phase 4.
- `web/nginx.conf`: `.mjs` served as `text/javascript` (module worker) with the strict CSP.

## [Unreleased] — #56: stable send e2e, compose fields wait for the draft

- W4/M4: Komu, Kópia, Predmet and the editor are disabled until the new draft exists. Text typed during a slow
  `POST /compose` was overwritten when the draft arrived (found as the flaky `phase1-issue23` desktop failure).
- `e2e/phase1-issue23.spec.ts`: deterministic send mock (first GET after send = queued, every later GET = sent /
  failed, independent of poll count), waits on the draft response and on the final payload instead of timing;
  new regression test for the race. 30× per test in both projects: 180/180 (also with 8 workers on 4 cores).

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
