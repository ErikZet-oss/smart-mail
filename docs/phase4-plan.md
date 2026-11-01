# Phase 4 plan — Money write: received delivery notes, customer orders, complaints (#188)

**Status:** **draft, waiting for Erik's approval.**
- No Phase 4 code, no migration and no write to Money until Erik approves this plan in #188.
- After approval, work goes milestone by milestone. Each milestone is one PR and stops for review.

**Scope and acceptance:** CLAUDE.md §7, §12 Phase 4.

**Binding behaviour:**
- `docs/DECISIONS.md` (D5, D6, D7, D11–D18)
- `docs/ORDERS_SPEC.md` (§1–§11, §13–§17)
- `docs/DOCUMENTS_SPEC.md` §2 (W6h, DL-B1–B10, DL-W1–W8)
- `docs/MONEY_API.md` §5.5–§5.8

**Facts used:**
- `probe_output/*.md` and `docs/probe-findings-2026-10-31.md`.
- Erik's decisions in #176:
  - centre only in the header of a received delivery note (DLP); items without `Cenik_ID`;
  - customer orders use the branch price list „bez DPH“.

**Priority rule (as in Phases 2–3):** pilot bugs and Phase 1–3 acceptance blockers always come first.

## Guards for the whole phase

- **TEST agenda only.** `MONEY_AGENDA_LABEL=TEST`.
  - The bridge already refuses writes on any other agenda (`writes_enabled` = public key set AND agenda TEST, ADR-017).
  - Production is a separate, explicit decision by Erik after Phase 4 acceptance. It is not part of this plan.
- **Every Money write needs:**
  - a human approval (autonomy ≤ 2, enforced in code);
  - the single-use Ed25519 approval JWT (ADR-017);
  - HMAC;
  - `SMID:<draft id>` at the start of `Poznamka`;
  - a duplicate check by SMID before the call;
  - **no automatic retry**. A timeout leads to reconciliation by SMID.
- **Main switch.** 13a „Zápisy do Money povolené“ is the switch for all writes. Each write feature also has its own feature flag and starts in **shadow mode** (§4).
- **Never guess a field, enum or GUID.**
  - Enum-like values (`DruhPohybu`, `DruhSkladovehoPohybu`, `TypCeny`, `Predkontace`, `CleneniDPH` …) are copied from the **branch template document** (DOCUMENTS_SPEC §2.6) or come from codebooks.
  - Every query and mutation is validated against `graphql_schema.json` in CI.
- **Smart Mail never edits an existing Money document** (`Edit…` replaces all items).
  - Corrections are a new document, or an undo within the window.
- **No stock handling and no packaging rounding** (D6, D17). No received invoices (D7). No fees (D14). No returns (D15).
- **Decimal end-to-end**: `numeric` columns; the `float(` gate covers `app/orders` and `app/purchasing` too.

## 1. Milestones

Order: everything around the received delivery note first, because it is the core flow (D7) and the first write. Customer orders follow, then complaints, new company/contact, and the Doklady hub. Every milestone ends with tests, lint, README/CHANGELOG and a review stop.

| # | Milestone | Scope | Screens (SCREENS_SPEC · FIGMA_MAP) | Settings | Tests (named by rule id) |
|---|---|---|---|---|---|
| **4a** | Supplier documents in — read only | Supplier invoice or delivery note from mail (supplier folders, D21) or from upload. Extraction: ISDOC/UBL → PDF tables (pdfplumber) + LLM → OCR + vision (D3), **all lines**. Validation and duplicates (DL-B1–B3 …). No write. | W6u `46:42624` (upload), W6e `46:41526` (list, state „Na kontrolu“), M13 `85:3245` | — | extraction golden fixtures (`expected.json`, fictional supplier PDFs); `test_DL_B*` for validation and duplicates; ISDOC/UBL parsers; property tests `parse_decimal` / `normalize_code` |
| **4b** | Item matching and W6h review — read only | Cascade: supplier code (`ArticleSuppliers`) → learned mapping → EAN → our code → open purchase order → fastener attributes → user. Unit conversion (no packaging rounding). Price and quantity checks. Branch warehouse. W6h as a copy of the Money card (DOCUMENTS_SPEC §2 field mapping). Learned mappings are confirmed by a person. | W6h `43:38227` (+ states), M13b `85:3565` | **14** Nákup a sklad (all fields, incl. Kódy dodávateľov) | `test_DL_W*`; matching cascade with fixtures of real supplier invoice shapes (fictional values); unit conversion; DL-W6 learned mapping; W6h e2e + Figma screenshot |
| **4c** | **First write: `CreateReceivedDeliveryNote` on TEST** | 11e completed: price list, warehouse, series, branch template document (`dl_template_money_id` + cached values). Bridge `POST /delivery-notes/received` (approval JWT, SMID, no retry). Read-back and comparison. Reconciliation after a timeout. **Undo** = `DeleteReceivedDeliveryNote` within 15 min (accounting, not invoiced). Shadow mode first (§4). | W6h states „V Money“ / „Vrátiť“, W6e | 11e (rest of the fields), 13a switch | idempotency: double approve, timeout after the mutation → reconcile, two users on one draft (409); `test_DL_B*` re-run at approval; bridge mock ↔ client contract; branch values (§5.5.9) on the payload: header centre, warehouse, series, no item `Cenik_ID`, no item centre (#176) |
| **4d** | Customer orders — read only and shadow | Detection, deterministic table parser + LLM extraction, customer identification and duplicates D1–D5 (`Odkaz` = customer PO, SMID), matching cascade with the critical-attribute guard, units, **prices (§2)**, W6f / M12 review. Per-customer templates. | W6f `48:42586` (+ states), M12 `85:3819` | **15** Objednávky (ORDERS_SPEC §16) | the whole ORDERS_SPEC §18 suite: B1–B14 / W1–W20, number formats, price-per units, code normalisation, no packaging rounding, critical attributes, duplicates D1–D5 |
| **4e** | Orders write | `CreateReceivedOrder` (items: branch warehouse) → read-back → W6g. Undo. Confirmation and clarification e-mails (snapshot tests). Changes and cancellations as a diff card + task + reply (W8d), **never `EditReceivedOrder`**. W8 list. | W6g, W8 `56:46543`, W8d `56:47238` | 15 (confirmation templates) | state machine and idempotency (ORDERS_SPEC §9), read-back equal, confirmation diff, e-mail snapshots |
| **4f** | Complaints | `CreateReceivedComplaint` from an e-mail; same write pattern (JWT, SMID, read-back, undo). | W8c `57:47788` | — | write pattern tests, extraction fixtures |
| **4g** | New company / contact | `CreateCompany` / person from a confirmed suggestion. IČO/DIČ/IČ DPH checks, duplicates by IČO and e-mail. | Zákazník panel W3b („Založiť v Money“), W9a | — | validation of IČO/IBAN/VAT, duplicates, write pattern |
| **4h** | Doklady hub, shadow reports, switch on | W6 hub with tabs Dodacie listy · Objednávky · Reklamácie · Upomienky; M13. Admin accuracy report of shadow mode (§4). Switch the create buttons on per feature after the threshold. | W6, M13 | — | e2e deep link per route; shadow comparison job tests |

Notes:
- **Phase 4 acceptance (CLAUDE.md §12):**
  - 10 supplier documents with ≥ 15 lines each → 10 received delivery notes;
  - ≥ 95 % of lines auto-matched after the second document of the same supplier;
  - stock increased in the branch warehouse, 0 duplicates, totals match;
  - 3 complaints;
  - all ORDERS_SPEC §18 fixtures pass;
  - 20 real orders from 10 customers: 0 wrong quantities or prices, 0 duplicates, read-back equal in 100 %, ≥ 90 % auto-matched for returning customers, median time from opening the card to the order created in Money < 60 s.
- **Mobile, Figma screenshots and axe:** every screen milestone includes the mobile counterpart, Playwright screenshots next to the Figma frames, and axe checks.

## 2. Customer order prices (`ORDER_PRICE_MODE`)

**Fact:**
- `ProdejniCeny(FirmaID)` returns 0 rows on TEST, also with `SkladID` (#176).
- Erik's decision: customer orders use the branch price list **„bez DPH“** (`10-bez DPH`, `20-…`, `30-…`, `40-…`).

**Proposal** (`ORDER_PRICE_MODE = branch_price_list`), in this order per line:
1. **An accepted offer exists** for the customer and article → the offer price (`price_source = offer`).
2. **Otherwise the branch price list „bez DPH“.** Read `PriceListItems(Filter:"Cenik_ID~eq~<branch list>#Artikl_ID~eq~<article>")` and take `Cena` (`price_source = price_list`, `price_meta = {Cenik_ID, TypCeny, MnozstevniSleva_ID}`).
   - If `ProdejniCeny` turns out to work with other arguments (probe `--phase4`), it is preferred, because it already applies Money's own discount logic.
3. **Company discount.** `HodnotaSlevy` applies only when Money applies it on its own documents.
   - The probe shows whether companies have it and whether price lists are assigned (`SeznamCeniku`).
   - Until that is confirmed, the discount is **shown, not applied**, and `price_reason` explains it.
4. **No rounding to packaging. No stock.** The quantity stays as the customer wrote it, after unit conversion (D6, D17).
5. **Customer price vs our price.** If the customer wrote a price and it differs beyond the tolerance (Settings 15), the line gets a warning (W-rule), never an automatic change.

**Read-only check on TEST:** `money_probe.py --phase4` (PR #190), steps „Branch price lists bez DPH“ and `ProdejniCeny` for an article from a branch price list. 4d starts only when the result confirms which field holds the price (`Cena`) and what `TypCeny` 0/1 mean for it. Meanings are copied from existing orders (`orders.md`: `TypCeny` 0 = 861, 1 = 35), never guessed.

## 3. The first Money write on TEST

Before any document write, the CRM activity (#189, Phase 3f) is tested as the very first write. It shows that the approval JWT, HMAC, SMID and read-back work end to end on the real API. That test is separate from this plan (#189).

**The first document write: `CreateReceivedDeliveryNote` (milestone 4c).**
- **Template document per branch.** Erik picks one received delivery note per branch (Trnava, Senica, Nitra, Trenčín) that was made by hand in Money, in Settings 11e „Vzorový dodací list pobočky“.
  - Smart Mail copies the enum-like values from it and caches them with the date: `DruhPohybu_ID`, `DruhSkladovehoPohybu_ID`, `TypCeny`, `Predkontace` (FP010 on all 300 notes), `CleneniDPH`, registration for VAT.
  - `money_probe.py --branches` with `PROBE_DL_NUMBER` / `PROBE_DL_DOKLAD_PRIJATY` confirms that „Doklad prijatý“ is stored in `Odkaz`. **Erik runs it once before 4c.**
- **Branch values on the write** (MONEY_API §5.5.9 as amended by #176):
  - header `Stredisko_ID` = branch centre;
  - items **without** `Stredisko_ID` and **without** `Cenik_ID`;
  - `ObsahPolozky.Sklad_ID` = branch warehouse (10/20/30/40; 99 never automatic, D11);
  - `CiselnaRada_ID` = branch series (`DLP TT/SE/NR/TN`).
  - Missing branch settings block the write.
- **Flow:**
  1. „Vytvoriť v Money“ (warehouse, accounting or admin) re-runs every DL-B rule.
  2. The main app signs the JWT (`act=create_received_delivery_note`, `sha256` of the payload, ≤ 300 s, `jti`).
  3. The bridge checks SMID (`ReceivedDeliveryNotes(Filter:"Poznamka~sw~SMID:<id>")`; this filter works on TEST, #176).
  4. The bridge sends the mutation once.
  5. Read-back by ID: compare lines, quantities, prices and totals; any difference → red banner.
  6. „Vrátiť“: `DeleteReceivedDeliveryNote` within 15 min, only when the note is not yet invoiced.
- **Timeout:** no retry. The draft goes to `reconciling`; the bridge looks it up by SMID. If found → `created`, if not → `failed` with „Skontrolujte v Money“.
- **What Erik prepares in Money (TEST):**
  - one template received delivery note per branch;
  - the series `DLP TT/SE/NR/TN` active;
  - warehouses 10–40;
  - the API role with rights for `CreateReceivedDeliveryNote` / `DeleteReceivedDeliveryNote` (and later `CreateReceivedOrder` / `DeleteReceivedOrder`, `CreateReceivedComplaint`, `CreateCompany`, Activity);
  - 2–3 suppliers with `ArticleSuppliers` codes for the test.

## 4. Shadow mode per feature (CLAUDE.md §0.1)

| Feature | Shadow behaviour | Measured | Threshold to switch on |
|---|---|---|---|
| Received delivery note (4c) | Drafts are created and reviewed on W6h; the create button is hidden. A nightly job compares the draft with the note made by hand in Money (same supplier + `Odkaz` = supplier document number). | Share of lines whose article, quantity and unit price are identical; share of lines auto-matched after the 2nd document of the same supplier | ≥ 95 % auto-matched after the 2nd document of the same supplier, measured over 2 weeks or 10 documents (whichever is later) |
| Customer orders (4d/4e) | Drafts on W6f; the create button is hidden. The nightly job compares with orders made by hand (same customer + `Odkaz` = customer PO; when `Odkaz` is missing, which is 199/200 today: customer + date + ±10 % total) | Share of identical lines (article, quantity, price) | ≥ 95 % identical lines after 2 weeks |
| Complaints, new company | Short shadow (1 week) with the same comparison | Correct fields | Erik's decision |

- The accuracy report is in Admin („Presnosť tieňového režimu“).
- The create button is switched on per feature by an admin, only after the threshold, with re-auth and an audit entry. Erik confirms each switch-on.

## 5. Data model changes (for approval before the first migration)

All with UUID PKs and `created_at` / `updated_at`. Money and quantity columns are `numeric`.

| Table | From | Purpose | Milestone |
|---|---|---|---|
| `documents` | CLAUDE.md §4 | supplier document in: source (mail/upload), kind (invoice/delivery_note), `extracted` (jsonb), `field_confidence`, `validation`, `status` (state machine), `branch_id`, `supplier_money_id`, `money_doc_id` / `money_number`, `idempotency_key` (unique), `version` (optimistic lock), `readback_diff`, `template_source` | 4a/4c |
| `document_lines` | DOCUMENTS_SPEC §2.4 | extracted line + matching: supplier code, EAN, name, qty, unit, unit price, `article_id`, `match_method`, `candidates`, `unit_factor`, warehouse, `line_status` | 4a/4b |
| `supplier_item_mappings` | MONEY_API §5.5.3 | learned mapping supplier + `code_norm` → article, unit factor, confirmed by/at, uses, last used; unique (supplier, code_norm) | 4b |
| `branches` (columns) | 11e | `money_price_list_id`, `money_warehouse_id`, `series_overrides`, `dl_template_money_id`, `dl_template_values`, `dl_template_cached_at` — **already exist** (Phase 1); nothing new expected | 4c |
| `order_drafts`, `order_draft_lines`, `customer_item_mappings`, `customer_order_templates` | ORDERS_SPEC §14 (exact columns there) | customer orders | 4d |
| `complaint_drafts` | new, minimal | complaint draft: company, source message, lines/description, status, SMID, Money id | 4f |
| `shadow_comparisons` | new | nightly result per feature/document: matched (bool), line stats (jsonb), compared Money id | 4c–4h |
| `feature_flags` | **exists** (migration 0013, key + person) | flags `write.delivery_notes`, `write.orders`, `write.complaints`, `write.companies` — rows only, no schema change | 4c |

Each table gets its own Alembic migration in the milestone that needs it. The list is approved once here; a change
later is asked again (CLAUDE.md §0).

## 6. Risks

- **Prices** (§2): if neither `PriceListItems` nor `ProdejniCeny` gives the price that people use, 4d stops until the Money implementer answers (MONEY_API §9 question 12).
- **Write rights of the API role** on TEST are not confirmed yet. The first write may answer 403.
- **Deleting a document (undo)** is untested. If `Delete…` is not allowed for the API role, undo becomes a task for a person in Money.
- **Comparing orders in shadow mode is harder**, because `Odkaz` is filled in only 1/200 orders made by hand. The fallback match (customer + date + total) can produce false pairs. The report shows which match was used.
- **Credit notes and other `TypDokladu` values** are unknown. Phase 4 does not depend on them (only the „posledná faktúra“ feature #182 does).
- **OCR quality** on scanned supplier documents. Golden fixtures cover text PDFs first; scans are measured in shadow mode.

## Otázka pre Erika

1. **Poradie míľnikov.** Navrhujem 4a–4c (dodací list prijatý až po prvý zápis), potom 4d–4e (objednávky), potom 4f reklamácie, 4g nová firma/kontakt a 4h Doklady a zapnutie. Súhlasíš?
2. **Ceny objednávok.**
   - Súhlasíš s `ORDER_PRICE_MODE = branch_price_list`: najprv cena z prijatej ponuky, inak `Cena` z cenníka pobočky „bez DPH“?
   - Zľavu firmy (`HodnotaSlevy`) zatiaľ iba zobrazím, kým neoverím, či ju Money na svojich objednávkach uplatňuje. Je to tak v poriadku?
   - Prosím spusti `money_probe.py --phase4` (#190).
3. **Vzorové dodacie listy.** Vyberieš v Money na TEST agende pre každú pobočku jeden ručne zadaný dodací list prijatý ako vzor? Spustíš `--branches` s `PROBE_DL_NUMBER` / `PROBE_DL_DOKLAD_PRIJATY`?
4. **Práva API roly.** Môže rola na TEST vytvárať a mazať `ReceivedDeliveryNote` a `ReceivedOrder`, vytvárať `ReceivedComplaint`, `Company` a `Activity`? Bez mazania nebude fungovať „Vrátiť“.
5. **Tieňový režim.** Súhlasíš s prahmi?
   - dodacie listy ≥ 95 % automaticky spárovaných riadkov po 2. doklade dodávateľa (2 týždne alebo 10 dokladov);
   - objednávky ≥ 95 % rovnakých riadkov po 2 týždňoch.
   - Tlačidlo „Vytvoriť v Money“ zapneš ty, po pohľade na report.
6. **Porovnanie objednávok bez `Odkaz`.** Ručné objednávky v Money majú číslo objednávky zákazníka iba v 1 z 200 prípadov. Je v poriadku párovať ich podľa zákazníka + dátumu + celkovej sumy (±10 %)? Alebo by ľudia mohli počas tieňového režimu vypĺňať `Odkaz`?
7. **Dátový model (§5).** Schvaľuješ tabuľky `documents`, `document_lines`, `supplier_item_mappings`, `order_drafts`, `order_draft_lines`, `customer_item_mappings`, `customer_order_templates`, `complaint_drafts`, `shadow_comparisons`? (`feature_flags` už existuje, pribudnú len záznamy.) Každá príde vo svojom míľniku s vlastnou migráciou.
8. **Dodávatelia na test.** Ktorí 2–3 dodávatelia (s kódmi dodávateľa v Money) a ktorí zákazníci budú na TEST agende na akceptáciu 4c a 4e?
