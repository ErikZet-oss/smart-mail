# ADR-011: Claude API (Anthropic) — data handling and cost

- Status: accepted (Phase 2a, 27 October 2026) — **DECISIONS D31**: provider is the Anthropic Claude API
  (`LLM_PROVIDER=anthropic`). This ADR is **not** a vendor comparison; AWS Bedrock stays an interface stub only.
- Context: Phase 2 plan binding addition C; CLAUDE.md §6 / §13; `docs/AI_ASSISTANT.md` §12.

## Decision

Smart Mail calls the **first-party Claude API** (`api.anthropic.com`) with `ANTHROPIC_API_KEY` from env / secret
file only. Model ids are **concrete values in env** (`LLM_MODEL_CLASSIFY`, `LLM_MODEL_DRAFT`, `LLM_MODEL_EXTRACT`,
`LLM_MODEL_ASSISTANT`, `LLM_MODEL_EMBED`) — never the string `latest`, never a hard-coded “current” alias in code.
The Bedrock client exists only as a stub so a future switch does not reshape the `LLMProvider` interface.

## Data handling (official Anthropic documentation)

Sources checked 27 October 2026 (Europe/Bratislava). If Anthropic updates a page, re-read it before go-live; this ADR
records the published position at acceptance, not a legal opinion.

### Where data is processed and stored

- Anthropic uses multiple cloud subprocessors; by default traffic may be routed to select countries in the US, Europe,
  Asia and Australia unless otherwise agreed or instructed.
  Source: [Where are your servers located?](https://privacy.claude.com/en/articles/7996890-where-are-your-servers-located-do-you-host-your-models-on-eu-servers)
- **Data is stored in the US.** Workspace geo for the Claude API is currently `"us"` only.
  Sources: same Privacy Center article; [Data residency](https://platform.claude.com/docs/en/manage-claude/data-residency)
- Inference geography can be pinned per request with `inference_geo` (`"global"` default, or `"us"`). There is no
  EU-only inference pin on the first-party Claude API as of this writing.
  Source: [Data residency](https://platform.claude.com/docs/en/manage-claude/data-residency)

### Retention

- For Anthropic API users, inputs and outputs are deleted on Anthropic’s backend **within 30 days**, except longer
  retention under the customer’s control (e.g. Files API), a different agreement (e.g. zero data retention), Usage
  Policy enforcement, or legal requirements.
  Source: [How long do you store my organization’s data?](https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data)
- Optional **zero data retention (ZDR)** (prompts/responses not stored at rest after the response) is available on
  request for eligible organizations/features.
  Source: [API and data retention](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention)
- Flagged Usage Policy content may be retained longer (up to 2 years for inputs/outputs; trust-and-safety scores up to
  7 years) per the same Privacy Center retention article.

### Training

- By default, Anthropic **does not** use inputs or outputs from commercial products (including the Anthropic API) to
  train models.
- Training on that data requires **express permission** or explicit opt-in (e.g. feedback / Development Partner
  Program).
  Source: [Is my data used for model training?](https://privacy.claude.com/en/articles/7996868-is-my-data-used-for-model-training)

### Roles and DPA

- For commercial Claude / API use, the customer is the **controller**; Anthropic acts as **processor** of customer
  data under the Commercial Terms.
  Source: [Does Anthropic act as a data processor or controller?](https://privacy.claude.com/en/articles/9267385-does-anthropic-act-as-a-data-processor-or-controller)
- The **Data Processing Addendum (DPA)** (with SCCs) is automatically incorporated into the
  [Commercial Terms of Service](https://www.anthropic.com/legal/commercial-terms). Accepting those terms accepts the
  DPA. Text: [How do I view and sign your DPA?](https://privacy.claude.com/en/articles/7996862-how-do-i-view-and-sign-your-data-processing-addendum-dpa);
  DPA document: [Data Processing Addendum](https://www.anthropic.com/legal/data-processing-addendum)

### Smart Mail hard rules (unchanged)

AI never sends outside the company and never writes to Money on its own; only mail received after `ai_enabled_at` is
processed; daily cap `AI_DAILY_BUDGET_USD`. Only AV-clean attachments are sent to the model; unscanned attachments do
not drop the e-mail — body text is still processed and the suggestion carries note code `attachment_unscanned`
(UI: `ai.notes.attachment_unscanned`). Application logs must not contain mail bodies or full model prompts/payloads —
only tokens, cost, latency, ids (`draft_id` / message UUID / purpose).

## Cost estimate (per 1 000 e-mails)

List prices from Anthropic’s pricing page (USD per million tokens), checked 27 October 2026:
[Pricing](https://platform.claude.com/docs/en/about-claude/pricing).

Code looks up rates by **exact model id** (`app/ai/pricing.py` → `MODEL_RATES`). Substring matching
(`"haiku" in model`) is forbidden — Haiku 4.5 must not be billed as Haiku 5.5. Unknown ids use the **highest**
rate in the table and log a warning (never under-estimate the budget).

| Exact API id (examples) | Input / MTok | Output / MTok | Notes |
|---|---|---|---|
| `claude-haiku-5-5` | **$0.10** (≤100K) / **$0.50** (>100K) | **$0.50** / **$2.50** | high-context tier on input size |
| `claude-sonnet-5-5` | **$2** | **$10** | |
| `claude-opus-5-5` | **$4** | **$20** | also the unknown-model fallback |
| `claude-haiku-4-5` / `claude-haiku-4-5-20251001` | **$1** | **$5** | distinct from Haiku 5.5 |

Assumptions for Smart Mail (order of magnitude for budgeting; real spend is logged per `ai_runs` row):

| Purpose | Env model slot | Assumed list price (≤100K context) | Assumed tokens / mail | **USD / 1 000 mails** |
|---|---|---|---|---|
| Classify | `LLM_MODEL_CLASSIFY` | Claude Haiku 5.5: **$0.10** in / **$0.50** out per MTok | ~1 500 in + ~200 out | **~$0.25** |
| Reply draft | `LLM_MODEL_DRAFT` | Claude Sonnet 5.5: **$2** in / **$10** out per MTok | ~3 000 in + ~500 out | **~$11** |

Calculation (classify on Haiku 5.5):  
`(1500/1e6)×0.10 + (200/1e6)×0.50 = $0.00025` per mail → **$0.25 / 1 000**.

Same tokens on Haiku 4.5:  
`(1500/1e6)×1 + (200/1e6)×5 = $0.0025` per mail → **$2.50 / 1 000** (must not equal the Haiku 5.5 figure).

Calculation (draft on Sonnet 5.5):  
`(3000/1e6)×2 + (500/1e6)×10 = $0.011` per mail → **$11 / 1 000**.

Notes:

- Token sizes vary with thread length, language, and prompt caching; drafts that include long quoted history cost more.
- US-only inference (`inference_geo=us`) is listed at **1.1×** those rates on the same pricing page.
- Batch API is 50 % off list; prompt-cache reads are cheaper — Smart Mail may use caching later; estimates above ignore
  those discounts.
- Daily budget day boundary is **Europe/Bratislava**; the budget is checked **before every LLM call** with an estimate
  of that call (a batch of N messages stops when the next estimate would exceed the cap).
- Install default budget: **`AI_DAILY_BUDGET_USD=5`**.

**Model ids are not pinned in this ADR.** Operators set dated / concrete API ids in `.env` (examples only in
`.env.example`). Code refuses empty model ids and the literal `latest`.

## Consequences

- New runtime dependency: official `anthropic` Python SDK (Messages API).
- `LLM_PROVIDER=bedrock` resolves to a stub that raises until a future decision replaces D31.
- Eval labeling stays on the server (`tools/eval_label.py`); no real mail in git.
