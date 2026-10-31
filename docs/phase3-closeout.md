# Phase 3 — close-out report (Money read)

Plan: `docs/plans/phase-3.md` (approved by Erik in #150, 30. 10. 2026; answers on 3f in #144, 31. 10. 2026).
This report closes the phase for review (CLAUDE.md §0, §12). **Phase 4 is not started.**

Everything runs against the **simulated Money** (mock bridge with fictional data). The real Money (TEST agenda) is
connected once the bridge is installed on the office server (3h) and `money_probe.py` has run there.

## Milestones

| # | Milestone | PR | Status |
|---|---|---|---|
| 3a | Bridge core + mock: read endpoints, HMAC, filter builder (hypothesis), mock + Money API backends, one contract suite | #153 | ✅ |
| 3b | Read cache (migration 0018) + sync (ChangeFrom delta, nightly full), worker, Settings 13a status / 13e sync | #158 | ✅ |
| 3c | Sender → company matching (MONEY_API §5.4), Zákazník panel W3b / M10, „Priradiť k firme“ | #160, #161 (Figma) | ✅ |
| 3d | invoice_attach: original Money PDF, owner checks at approve **and at send**, „Poslať“, Settings 13b | #162 | ✅ |
| 3e | W8b Upomienky: debtors, one reminder draft per customer (E2 + PDFs), history | #163 | ✅ |
| 3g | W9a Zákazník 360, Money in global search and Ctrl+K | #164 | ✅ |
| 3h | Bridge on the Windows Server (NSSM + Cloudflare Tunnel/Access), SK install guide, ADR-016 | #165 | ✅ |
| 3f | CRM activity after send — first Money write, Ed25519 approval token (ADR-017), 13a writes switch, 13d | #166 | ⏳ in review |

Also in the phase: #156/#157 suggestion cards collapsed by default; #159 duplicate i18n key (reviewer).

## Acceptance (CLAUDE.md §12 Phase 3)

| Criterion | Proof | Status |
|---|---|---|
| 10 real invoice requests end to end, **0 wrong-recipient sends** | On the mock: `tests/test_money_3d.py` — owner check at evaluate, live again at approve, **again at send** for every to/cc/bcc (a changed recipient is blocked); a foreign invoice never enters a draft or a card. Real requests: after the bridge runs on TEST | ⏳ real run on TEST (needs 3h installed + probe) |
| Money offline does not break mail | Circuit breaker; every Money surface has a „Money nedostupné“ state (13a, panel parts, W8b, W9a, search); the send never waits for Money; tests per surface | ✅ (mock / tests) |
| Contract tests | one suite for mock (CI) and TEST (`--money-live`); `fixtures/money/bridge_contract.json` checked by bridge and app | ✅ mock · ⏳ TEST |
| Schema drift | `tools/validate_graphql.py` in CI (queries + docs blocks), swagger paths from the files | ✅ |
| No floats / strict typing | `float(` gate in CI (also caught one in 3f), mypy strict app + bridge | ✅ |
| Screens match Figma | Figma MCP not reachable from this session (403); the reviewer compared 3c and the follow-up #161 was built from it. Screenshots of every new screen are in the e2e artifacts | ⏳ review of W8b, W9a, W12-13a/b/d/e |

## Gates (local run, 31. 10. 2026)

| Gate | Result |
|---|---|
| ruff + format, mypy strict (app 139 files, bridge 15) | ✅ |
| pytest (app) | ✅ 854 passed, 22 skipped (IMAP/Sieve integration in CI); golden prints run in CI (no Narrow font locally) |
| pytest (bridge) | ✅ 82 passed, 10 skipped (`--money-live` variants) |
| vitest | ✅ 212 passed (incl. route manifest W8b, W9a) |
| tsc, eslint, prettier | ✅ |
| Playwright | ✅ phase3b–3g specs desktop + mobile; full suite in CI |
| schema drift, float gate, PowerShell parse (CI) | ✅ |

## Waiting for the probe (never guessed)

- REST filter syntax → Activity list per company, proforma search, the SMID check before an activity write
  (until then: 501 `waiting_for_probe` on the real API, works on the mock).
- `Person.parent_ID` = company (matching step „Money person“).
- Required fields of `ActivityInputDto`; meaning of `Stav` / `Vyrizeno` / `TypDokladu` (shown raw / not shown).
- Bank details for the reminder text (`MojeFirmaBankovniSpojeniIBAN` not read yet).

## Needed from Erik

1. Install the bridge on the Money server (README › „Bridge na serveri Money“) and run `money_probe.py` on the TEST
   agenda (README › „Spustenie money_probe.py na Windows Serveri“); send `probe_output/*.md`.
2. Report ids in Settings 13b; activity types in 13d; then switch on 13a when ready.
3. 10 real invoice requests on TEST (acceptance), and the Figma review of the Phase 3 screens.

## Open items and risks

- `threads.money_company_id` is not stored (computed when the panel opens); a small migration if a later phase
  needs it — „Otázka pre Erika“ then.
- The Windows scripts are parse-checked in CI but have not run on a real Windows Server yet; the first install is
  their test (send the PowerShell output without passwords if it fails). Windows Server 2019 has no winget.
- Phase 4 writes reuse the approval token (ADR-017) with their own `act`; the bridge `writes_enabled` already
  requires the public key and the TEST agenda.
