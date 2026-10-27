# Phase 2 plan — AI triage & drafts (proposed 27 October 2026, awaiting customer approval)

**Status:** plan only — **do not start coding until this document is approved.**  
**Phase 1 code** is complete on `main` (PR #14 / 1h-e merged). **Phase 1 acceptance** remains the pilot on a
**real mailbox** (CLAUDE.md §12 Phase 1) — that gate is not closed by CI alone.

**Priority rule:** pilot bugs and Phase 1 acceptance blockers **always take priority** over Phase 2 work. Pause or
preempt any Phase 2 milestone when a pilot issue lands.

Scope and acceptance: CLAUDE.md §6 and §12 Phase 2; binding behaviour: `docs/AI_ASSISTANT.md` (autonomy, pipeline,
guards, prompts, eval); screens: `docs/FIGMA_MAP.md` / `docs/SCREENS_SPEC.md`; settings: `docs/SETTINGS_SPEC.md`
§07 and §17. Decisions: `docs/DECISIONS.md` (esp. D8 autonomy per login).

Guards for this phase (same as Phase 1, plus AI): no real external send without approval; AI never sends outside the
company and never writes Money (max autonomy level 2 for those actions — hard-coded); no PRODUCTION Money agenda;
no real customer data in fixtures; all UI strings in `web/src/i18n/sk.json`; AV-clean attachments only for AI
(`av_status = clean`, AI_ASSISTANT §2 / §9).

**Out of Phase 2 (later phases):** full Asistent chat panel (W3 / Phase 5), Dnes briefing UI & digest (W5 / Phase 5),
Money read/write (Phases 3–4), Web Push, batch approve on Dnes, order/delivery-note proposals. Settings fields in
W12-07 that only apply to Dnes / follow-ups / assistant history may be stored in Phase 2 but must not drive unfinished
screens.

---------------------------------------------------------------------------------------------------

## Acceptance (CLAUDE.md §12 Phase 2)

| Criterion | How we prove it |
|---|---|
| ≥ 90 % category accuracy on the labeled set | `make eval` on labeled CSV (≥ 200 mails); CI regression gate (must not drop > 2 points) |
| Drafts in the right language | eval draft-language check + fixtures per language (sk/cs/en/de at minimum) |
| Injection suite passes | ≥ 20 malicious fixtures (AI_ASSISTANT §12); required before each release |
| Autonomy hard rules | unit tests: external send & Money writes capped at level 2; approve re-runs guards |
| Shadow mode | feature flag: suggestions created, hidden in UI; admin can inspect accuracy |
| Settings 07 + 17 | schema + UI from SETTINGS_SPEC; snapshot vs spec in CI |
| Screens match Figma | side-by-side Playwright vs FIGMA_MAP for Phase 2 frames (W2f, W4a, AiSuggestionCard, W12-07, W12-17a–f, M17) |

Phase 1 pilot acceptance (real mailbox day, Filtre ↔ Roundcube, branch signatures in audit, PWA, axe, Figma review)
stays open until the customer confirms — it is **not** replaced by Phase 2.

---------------------------------------------------------------------------------------------------

## Milestones (order of work)

Work in milestones; after each: all CI gates green, push, stop for review. Do not start the next milestone without
approval. Prefer small PRs.

| # | Milestone | Screens / surfaces | Content |
|---|---|---|---|
| **2a** | Provider, data model, pipeline skeleton | — (backend) | `LLMProvider` (Anthropic + Bedrock EU stubs/impl behind env); models from env; `ai_runs` / `classifications` / `ai_suggestions` tables (or extend existing); worker hook on new mail (subscribed folders, D21 exclusions); AV gate; idempotency per `Message-ID`; cost logging hooks; feature flag `ai_shadow_mode` |
| **2b** | Classify + AI views | W2f (AI triedenie), list badges | Deterministic rules first (AI_ASSISTANT §2); classify JSON schema (§4); language detection; AI category views / filters; list summaries toggle (SETTINGS 07); private-folder skip; phishing / DMARC banners (guard basics) |
| **2c** | Reply suggestions | reading pane `AiSuggestionCard`, approve/reject | Plan step for **reply** only (no Money tools yet); guards (§9) that apply without Money; draft into Koncepty on approve path level 2; reject reason chips; audit `ai` / `user`; shadow mode hides cards |
| **2d** | Compose AI panel | W4a, M17 | Napíš / Prepíš / Prelož / Kontrola pred odoslaním; diff preview (Formálnejšie etc.); never invent signature; uses active person style when available |
| **2e** | Style, knowledge, NL rules | W12-07 (person), W12-17d–e (admin) | Style guide + knowledge cards (embeddings later ok with pgvector); NL → structured rules with confirm; personal style profile opt-in (per person, PRODUCT_SPEC §2.0) |
| **2f** | Autonomy, budget, shadow, eval | W12-07 autonomy matrix, W12-17a–c, W12-17f | Autonomy per login (D8); cost budget; admin provider/budget/categories; shadow + accuracy/consumption; `make eval` + injection suite in CI; labeled CSV process documented |

**Suggested PR mapping:** one PR per milestone (2a…2f), same pattern as Phase 1h. Merge only after review; pilot fixes
may interrupt the sequence.

---------------------------------------------------------------------------------------------------

## Order of work (dependencies)

1. **2a before anything UI** — no LLM calls from the web without the provider, worker, and schema.
2. **2b before 2c** — categories and views feed which threads get reply cards.
3. **2c before 2d** — shared draft/guard stack; compose panel reuses draft prompts.
4. **2e in parallel with late 2c/2d** only after 2a (needs embeddings / storage); rules must execute deterministically after confirm.
5. **2f last for gates** — eval corpus and injection suite must be green before calling Phase 2 “done”; shadow mode should exist from 2c but admin accuracy UI can land in 2f.
6. **Money-backed propose tools** stay stubs or absent until Phase 3 (invoice_attach, etc.) — Phase 2 proposals are
   mail-side (reply / rewrite / translate / pre-send check).

---------------------------------------------------------------------------------------------------

## What is needed from the customer

Not all items block 2a; call out blockers explicitly.

| Need | Blocks | Notes |
|---|---|---|
| **Phase 1 pilot day on a real mailbox** (or written waiver) | Declaring Phase 1 accepted | Filtre/Mimo ↔ Roundcube; branch picker + signature in audit; real host `mail.nameserver.sk` / agreed mailbox |
| LLM provider choice + credentials | Live classify/draft in non-mock env | Anthropic and/or AWS Bedrock **EU**; keys only in env/secret store, never git/chat |
| Model IDs for classify / draft / embed (and later assistant) | Production quality | Env names in CLAUDE.md §13; can start with documented defaults in TEST |
| Labeled eval CSV (≥ 200 e-mails, fictional or anonymised) | Acceptance ≥ 90 % | Categories per AI_ASSISTANT §4; no real customer secrets in the repo — use private CI secret or encrypted fixture agreed with Smart |
| Confirmation of shadow-mode pilot week | Turning suggestions visible | First week: create suggestions, hide in UI, measure accuracy (AI_ASSISTANT §2) |
| Review of Figma Phase 2 frames (W2f, W4a, W12-07, W12-17*, M17) | UI milestone sign-off | Same side-by-side process as Phase 1 |
| VIP list / urgency hints (optional) | Better urgent classification | Can start empty |

---------------------------------------------------------------------------------------------------

## Explicit non-goals in Phase 2

- Implementing Phase 3–7 features “because the model can”.
- Full W3 Asistent agent loop, slash commands, global palette AI groups (Phase 5).
- W5 Dnes briefing generation and digest e-mail (Phase 5) — settings may exist, behaviour waits.
- Any Money GraphQL/REST write or invoice PDF attach (Phase 3+).
- Orders / received delivery notes AI extraction (Phase 4).
- Starting Phase 2 implementation PRs before **this plan is approved**.

---------------------------------------------------------------------------------------------------

## Risks

- Eval set quality and leakage (must stay out of prompts as free-form customer PII).
- Provider latency / EU residency vs Bedrock region choice.
- Shadow mode UX confusion if cards are half-visible.
- Scope creep into W3/W5 or Money tools.
- Pilot bugs delaying the calendar — **accepted**; quality of Phase 1 wins.

---------------------------------------------------------------------------------------------------

## Definition of done for the phase

Acceptance table above green + quality gates in CLAUDE.md §0.1 that apply (strict typing, no mail bodies in logs,
injection suite, eval gate) + README/CHANGELOG updated + open risks listed + **stop for review**. Do not start
Phase 3 on your own.
