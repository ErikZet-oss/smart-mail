# Phase 2 — close-out report (AI triage & drafts)

Plan: `docs/plans/phase-2.md` (approved 27. 10. 2026). This report closes the phase for review (CLAUDE.md §0, §12).
**Phase 3 is not started.** Its plan is in #144 / `docs/plans/phase-3.md` and waits for approval.

## Milestones

| # | Milestone | Done in | Status |
|---|---|---|---|
| 2a | Provider, data model, pipeline skeleton (`ai_enabled_at`, AV gate, idempotency, cost log, shadow flag) | #16 (+ #99 reply step) | ✅ |
| 2b | Classify + AI views (W2f, rules first, language, private-folder skip, phishing/DMARC banners) | #17, #104, #126, #141 | ✅ |
| 2c | Reply suggestions — AiSuggestionCard, approve → draft in Koncepty, guards re-run, reason chips | #99, #105, #106, #132, #135, #136 | ✅ |
| 2d | Compose AI panel W4a / M17 — napíš, prepíš, prelož, kontrola pred odoslaním | #107–#109 | ✅ |
| 2e | Style guide + knowledge cards (full-text, ADR-014), NL rules, personal style profile | #111–#115 | ✅ |
| 2f | Autonomy per login (D8), budget, 17a–c/f, shadow switch, accuracy, eval, injection suite | #116–#118, #124–#126, #129 | ✅ |

Added during the phase on Erik's request (outside the original milestones):
- #127 backup to ZIP and purge after backup (#130, #134 — #134 is still in review).
- #139 Prehlásenie o zhode, parts A–C (#140, #146, #147 — part C is in review).
- #143 Zmeniť kategóriu / Znova zaradiť (AI) (#148 — in review).

## Acceptance (plan › Acceptance)

| Criterion | Proof | Status |
|---|---|---|
| ≥ 90 % category accuracy on the labeled set | `make eval` on the server (#129); the confusion table is in 17f; manual corrections from #143 add labels (`--labels-from corrections`) | ⏳ **needs the server run** on ≥ 200 labeled mails — the result is not in git (real mail stays on the server) |
| Drafts in the right language | `test_2b_language_sk_vs_en`, `test_2c_guard_security_attachment_and_language_warnings`, `test_2d_language_check`; Slovak named in full in prompts (#136) | ✅ in tests; ⏳ confirm in the shadow week |
| Injection suite passes | `make injection`: 22 fictional cases (`fixtures/ai/injection/cases.json`, #117) | ✅ |
| Autonomy hard rules | `test_116_hard_actions_never_above_2_whatever_is_stored`; approve re-runs guards (2c tests) | ✅ |
| Shadow mode | `ai_shadow_mode` fail-safe ON without a row; admin switch + accuracy in 17f (#118) | ✅ — **stays ON** |
| History not auto-processed | `test_2a_first_sync_of_10000_old_messages_makes_zero_llm_calls`, `test_2a_backfill_estimate_requires_count_cost_and_limit`; „Znova zaradiť“ also refuses mail from before `ai_enabled_at` (#148) | ✅ |
| Settings 07 + 17 | schema in `web/src/features/settings/schema.ts` + backend; snapshot test vs SETTINGS_SPEC | ✅ |
| Screens match Figma (W2f, W4a, AiSuggestionCard, W12-07, W12-17a–f, M17) | side-by-side in each UI PR | ⚠ the Figma MCP server is not reachable from this session (proxy 403), so no new side-by-side for this report — **customer review of the frames is open** |

## Gates (local run, 30. 10. 2026, main at `d2c4cf8`)

| Gate | Result |
|---|---|
| ruff check + format | ✅ clean |
| mypy strict (`app/`, `bridge/`) | ✅ no issues (125 + 4 files) |
| pytest | ✅ 759 passed, 22 skipped (IMAP/Sieve/SMTP integration runs in CI with Dovecot); 3 golden-print tests fail **only locally** because this container has no Liberation Sans Narrow — they run green in CI, which installs the font |
| vitest | ✅ 203 passed |
| tsc --strict, eslint, prettier | ✅ clean |
| pip-audit | ✅ no known vulnerabilities |
| npm audit | ⚠ 4 low, 2 moderate (no high; CI gate `--audit-level=high` is green) |
| injection suite | ✅ 22 cases (part of pytest) |
| Playwright e2e | runs in CI on every PR (not rerun locally for this report) |

## Open items and risks

- **Server eval (≥ 90 %)** and the **end of the shadow week** decide when suggestions become visible. Erik runs `make eval` on
  the server and switches shadow off in 17f; until then shadow stays ON.
- Stored but not wired yet:
  - 17a „Upozorniť pri (%)“ — no alert yet; it needs 08 Notifikácie (Phase 5);
  - 17a „Uchovávať záznamy AI“ — no purge job for `ai_runs` / classifications yet;
  - 17a provider is read-only from env.
- Embeddings (`LLM_MODEL_EMBED`) stay off (ADR-014). Turn them on only if the eval shows missed knowledge.
- #121 flaky `npm test` on CI: #145 added annotations with the test name and a TZ-independent date test. No new failure
  has shown up since. If one does, the annotation names the test and it gets fixed in its own PR.
- Phase 1 pilot acceptance (real-mailbox day, Filtre ↔ Roundcube, Figma review) is still open — Erik's waiver of
  29. 10. (#94) let Phase 2 run in parallel; it does not replace that acceptance.
- Open PRs: #134 (re-reviewed, merges after green CI), #147, #148.

## Needed from Erik

1. Run `make eval` on the server (≥ 200 labels) and post the accuracy (no mail content).
2. Decide the end of the shadow week → switch in 17f.
3. Review the Phase 2 Figma frames (W2f, W4a, AiSuggestionCard, W12-07, W12-17a–f, M17).
4. Approve the Phase 3 plan (#144).
