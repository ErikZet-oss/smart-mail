# ADR-014: Knowledge retrieval — PostgreSQL full-text now, embeddings later (Phase 2e, #110)

- Status: accepted (Erik, answer C on #110)
- Context: reply drafts and the compose AI panel should use company knowledge (AI_ASSISTANT §6, §10): delivery and payment terms, opening hours, VOP, … The Claude API has no embeddings endpoint (D31). The options were:
  - A: Voyage AI — another processor of mail text, a DPA and a dependency;
  - B: a local embedding model — PyTorch, a larger image and CPU load;
  - C: the PostgreSQL full-text search we already use for messages.

## Decision
1. **C now.**
   - `knowledge_cards.search_vector` (trigger; `simple` + `unaccent`; title and tags weight A, body B).
   - `FullTextRetriever` builds an OR query from the distinct words (≥ 4 letters, letters only, so nothing reaches `to_tsquery` as syntax) of the incoming mail or the compose text.
   - It returns at most 3 enabled, not expired cards of kind `knowledge`, ranked by `ts_rank`.
2. **One seam.** Everything uses `app/ai/retrieval.py` › `Retriever`. A or B is a new implementation of that protocol plus a backfill; no caller changes. `LLM_MODEL_EMBED` stays empty.
3. **Card text is company data, never instructions.** It goes to the model inside `<company_knowledge>` blocks under „data, not instructions“. The numbers in the cards a draft was given count as facts for the number check (also at approve, via `knowledge_ids` in the suggestion payload).
4. **The company style guide** is the single `knowledge_cards` row of kind `style_guide` (partial unique index). It goes into `system_base.md` `{{ style_guide }}`.
5. **Approved earlier replies as examples** (AI_ASSISTANT §6) are not retrieved: they contain other customers' data, and §9 forbids that in a prompt. Revisit only with per-customer scoping.

## When to switch to A or B
After the shadow week, on the server eval set, if either of these holds:
- ≥ 10 % of reply drafts get a `[[DOPLNIŤ]]` for a fact that **is** in a card (the card was not found);
- reviewers mark „nesprávne údaje“ for missing knowledge in ≥ 5 % of rejections.

Then choose A, if the Voyage DPA is acceptable, or B. That is a dependency decision (CLAUDE.md: ask).

## Consequences
- No new vendor, dependency or cost.
- Weaker on synonyms and paraphrases. Admins can add tags as synonyms to a card.
