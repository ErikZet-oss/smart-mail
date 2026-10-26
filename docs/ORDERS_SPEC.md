# ORDERS_SPEC.md — customer orders from e-mail → Objednávka prijatá in Money S4 (v2.6)

Binding spec for the whole "customer order" feature: detection, extraction, customer and item matching, pricing,
review screen, writing to Money, order confirmation e-mail, changes/cancellations, status tracking.
Read together with `MONEY_API.md` (§2 conventions, §5.6 calls), `AI_ASSISTANT.md` (§4, §7, §9) and `UX_SPEC.md` (W6f,
M8). Field names below are copied from `bridge/schema/graphql_schema.json` — do not rename, do not guess others.
Items marked **[PROBE]** must be verified on the TEST agenda (`tools/money_probe.py --orders`) before Phase 4 code
relies on them; until then the documented fallback applies.
**Scope decision D6 (DECISIONS.md):** the order is written to Money as Objednávka prijatá; stock is not handled
(no availability, no shortage decisions, no reservation) and quantities are not rounded to packaging.

Rule zero: **nothing is written to Money and nothing is sent to the customer without an explicit approval of an
authenticated user with role `sales`, `accounting` or `admin`** (autonomy max level 2 for `order_create` and
`order_confirmation`, enforced in code).

---------------------------------------------------------------------------------------------------
## 1. Scope

In scope:
- New orders from customers sent by e-mail: in the body, as attachment (PDF text, scanned PDF/image, XLSX/XLS, CSV,
  DOCX), as UBL 2.1 `Order` XML, or as a reply accepting our offer ("objednávame podľa ponuky PV263415").
- One e-mail with several purchase orders (one draft per PO), one PO split across several e-mails (follow-up adds
  lines → handled as change, §11).
- Changes and cancellations of existing orders (detected, diffed, prepared — not auto-applied in Money, §11).
- Order confirmation e-mail to the customer (§10) and status tracking until delivered (§12).

Out of scope (v1):
- **E-shop orders.** They reach Money directly through the e-shop integration (confirmed, D6). E-mails from the
  e-shop (sender list in Settings › Objednávky › "Ignorovať odosielateľov") are classified `notification` and never
  produce an order draft — otherwise duplicates in Money.
- **Stock and packaging (D6):** no availability check, no stock status, no backorder/partial/substitute decisions,
  no reservation, no rounding to packaging or minimum order.
- Editing or deleting orders in Money (except undo of our own just-created order, §9.6).
- EDI channels other than e-mail.

---------------------------------------------------------------------------------------------------
## 2. End-to-end flow (happy path)

```
IMAP new message
 → pipeline: parse → classify (order | order_change | order_cancel | inquiry …)          AI_ASSISTANT §2, §4
 → order_detect: is it really an order? (rules §3)  ── no → normal inquiry/offer flow
 → extract header + lines (deterministic first, LLM second)                                §4
 → identify customer (company + person)                                                    §5
 → duplicate check (Money + local)                                                         §6
 → match each line to an article (cascade)                                                 §7
 → quantities: unit conversion (no packaging rounding, D6)                                 §8.1
 → prices: offer / ProdejniCeny / customer price comparison                               §8.2
 → warehouse = branch warehouse (no stock check, D6)                                       §8.3
 → header defaults: series, transport, payment, delivery address, notes                    §8.4
 → validation (blocking B-rules, warnings W-rules)                                         §13
 → order draft + AiSuggestionCard "Objednávka" in the thread + row in Doklady › Objednávky
 → user opens review screen W6f, resolves amber/red items, clicks "Vytvoriť objednávku v Money"
 → backend re-runs everything (§13), takes approval token, bridge CreateReceivedOrder      §9
 → read-back + compare; success → draft of order confirmation e-mail (§10) appears
 → user approves confirmation → SMTP send (undo 10 s) → REST Activity in Money
 → status sync until delivered (§12)
```
Target time for a returning customer with known codes: < 60 s from opening the card to created order.

---------------------------------------------------------------------------------------------------
## 3. Order detection

Classification output (AI_ASSISTANT §4) gives `category` and `confidence`. Then deterministic rules in
`app/orders/detect.py` (pure function, unit-tested):

| Signal | Effect |
|---|---|
| Attachment named/titled `Objednávka`, `Objednavka`, `Bestellung`, `Purchase Order`, `PO`, `Zamówienie`, `Rendelés` with a number | strong order |
| Phrases: "objednávame", "záväzne objednávame", "prosím dodať", "bitte liefern", "we order", "please supply", "objednávka č." | order |
| Reply in a thread where we sent an offer + "súhlasíme / objednávame / potvrdzujeme ponuku" | order from offer (§4.4) |
| Phrases: "cenová ponuka", "prosím o ponuku", "koľko by stálo", "Angebot", "quotation", "RFQ" | inquiry (not order) |
| Mentions existing order number / customer PO + "zmena", "doplniť", "navýšiť", "znížiť", "storno", "zrušiť" | order_change / order_cancel |
| Sender in e-shop ignore list | notification (never an order) |
| Internal sender (INTERNAL_DOMAINS) forwarding a customer e-mail ("FW:", "Fwd:") | process the forwarded original; customer = original sender (parse `message/rfc822` or quoted headers) |

If the classifier says `order` with confidence < 0.75 or rules conflict → card shows chip **"Je to objednávka?"**
with buttons Áno / Nie, je to dopyt (feedback is stored for evaluation). No extraction cost before Áno if the
conflict is between order and inquiry.

---------------------------------------------------------------------------------------------------
## 4. Extraction

### 4.1 Source priority (stop at the first that yields lines)
1. **UBL 2.1 Order XML** → deterministic parser (`documents/ubl_order.py`).
2. **Reference to our offer** (offer number found, or reply in offer thread) → lines copied from the Smart Mail
   offer (articles, prices, quantities already known); the e-mail text only adds deviations ("ale len 1 000 ks").
3. **XLSX/XLS/CSV** → deterministic table parser with column mapping by header synonyms (table below); mapping can be
   saved per customer (`customer_order_templates.column_map`). LLM is used only to propose a mapping for unknown
   headers, never to read cell values.
4. **PDF with text layer** → `pdfplumber` tables first; if tables are irregular → LLM over the extracted text with
   page/line references.
5. **Scanned PDF / image** → `ocrmypdf` (slk, ces, deu, eng) → step 4; if OCR quality is low → LLM vision.
6. **E-mail body** (plain text or HTML table) → HTML tables deterministic, free text → LLM.

Header synonyms for tables (case/diacritics-insensitive): code = {kód, kod, číslo, cislo, art. č., obj. č., Artikel,
Art.-Nr., item, part no, SKU, katalógové číslo}; name = {názov, popis, tovar, Bezeichnung, description}; qty =
{množstvo, mnozstvo, počet, ks, Menge, qty, quantity}; unit = {MJ, m.j., jednotka, Einheit, unit, UoM}; price =
{cena, j. cena, cena/MJ, Preis, unit price, EP}; ean = {EAN, čiarový kód, GTIN}; date = {termín, dodať do, Liefertermin,
delivery date}.

### 4.2 Extraction schema (JSON returned by `extract_order`, validated by Pydantic; unknown keys rejected)
```json
{
  "document_kind": "order|order_change|order_cancel",
  "customer_po_number": "string|null", "po_date": "YYYY-MM-DD|null",
  "customer": {"name": "", "ico": "", "dic": "", "ic_dph": "", "address": {...}},
  "contact": {"name": "", "email": "", "phone": ""},
  "billing_address": {"name": "", "street": "", "city": "", "zip": "", "country_iso2": ""} ,
  "delivery_address": {"name": "", "street": "", "city": "", "zip": "", "country_iso2": "", "note": ""},
  "requested_delivery": {"date": "YYYY-MM-DD|null", "text": "napr. 'čo najskôr', 'KW 46'"},
  "transport_text": "osobný odber | kuriér | vaša doprava | …|null",
  "payment_text": "string|null", "currency": "EUR|CZK|…|null",
  "offer_reference": "string|null",
  "certificates_required": "none|2.2|3.1|unknown", "notes": "string|null",
  "stated_total": {"amount": "decimal-string|null", "with_vat": true},
  "lines": [{
    "line_no": 1,
    "customer_code": "string|null", "our_code_guess": "string|null", "ean": "string|null",
    "text": "raw description exactly as written",
    "attributes": {"norm": "DIN 933", "d": "M10", "length_mm": 30, "material": "A2", "strength": null,
                   "finish": null, "pitch": null},
    "quantity": "decimal-string|null", "unit_text": "ks|bal|kg|…|null",
    "price": "decimal-string|null", "price_per": 1, "currency": "EUR|null",
    "requested_date": "YYYY-MM-DD|null", "note": "string|null",
    "source": {"kind": "pdf|xlsx|csv|body|xml|offer", "page": 1, "bbox": [x0,y0,x1,y1], "sheet": "", "cell": "",
               "text_span": [start, end]},
    "confidence": {"code": 0.0, "quantity": 0.0, "price": 0.0, "text": 0.0}
  }]
}
```
Rules for the extractor (enforced by validators after the LLM call):
- **Never invent values.** Missing quantity → `null` (blocking B4 later), never 1.
- Numbers come as **strings** and are parsed by `parse_decimal(text, locale_hint)`: SK/CZ `1 000,50`, DE `1.000,50`,
  EN `1,000.50`; ambiguous `1.000` / `1,000` → use customer locale (country of company, language of e-mail); if
  still ambiguous → flag `ambiguous_number` (warning W16, the user confirms). Never `float`; use `Decimal`.
- `price_per`: detect "cena za 100 ks", "/100", "%" in price column header ("EUR/%" = per 100 in DE), "/1000",
  "‰", "per M", "/C" → 100 or 1000; convert to unit price = price / price_per with 6 decimals.
- Units normalized by table: ks/kus/kusov/pcs/pc/Stk/St./ST → `ks`; bal/balenie/bal./pack/pkg/VE/Pck → `bal`;
  kg; m; tis./tisíc/M (only when header says "v tisícoch") → factor 1000 on quantity. Unknown unit → keep text,
  warning W17.
- Line order preserved; subtotal/total/shipping lines of the customer document are not items (`kind:"summary"`
  filtered out); "doprava" requested by customer goes to header `transport_text`.
- Every line keeps its `source` so the review screen can highlight it in the original.

### 4.3 Validation after extraction
Row count sanity: the number of extracted lines must equal the number of table rows detected deterministically
(when a table exists) — mismatch → warning W18 "Možno chýba riadok" with highlighted gaps. Duplicate lines (same code
twice) are kept separate (customers do that on purpose) but flagged info.

### 4.4 Order from our offer
If `offer_reference` matches an offer in Smart Mail (`offers.number`) for the same company:
lines = offer lines (article, qty, price, warehouse). Offer expired (`valid_until` < today) → warning W14; prices
then re-checked against `ProdejniCeny` and the higher/lower difference shown; the user chooses "cena z ponuky" or
"aktuálna cena". Offer status → `accepted` only after the Money order is created.

---------------------------------------------------------------------------------------------------
## 5. Customer identification

1. Sender address → company/person using MONEY_API §5.4 (confirmed links first).
2. Cross-check with document data: IČO/DIČ/IČ DPH on the PO (`Companies(Filter:"ICO~eq~<ico>")`).
3. Results:
   - Same company from both → OK.
   - Sender's company ≠ company on PO (e.g. purchasing department of a group) → **blocking choice B12** "Objednávka je na
     firmu X, odosielateľ patrí k Y" — the user picks; the choice can be remembered as a link (sender → company).
   - Not found → suggestion `company_create` first (prefilled from PO: name, IČO, DIČ, IČ DPH, address, e-mail), the
     order card waits in state `needs_input`.
4. Company context loaded once per draft: `Company(ID){ Nazev ICO DIC ICDPH Mena_ID ZpusobPlatby_ID ZpusobDopravy_ID
   SplatnostPohledavek VlastniSplatnostPohledavek HodnotaSlevy VlastniSleva PouzivatKredit HodnotaKreditu
   CinnostUkoncena DatumUkonceniCinnosti Poznamka ObchNazev ObchUlice ObchMisto ObchPsc ProvNazev ProvUlice ProvMisto
   ProvPsc OdlisnaAdresaProvozovny FaktNazev FaktUlice FaktMisto FaktPsc OdlisnaFakturacniAdresa SeznamCeniku{…} }`
   + receivables `IssuedInvoices(Filter:"Firma_ID~eq~<C>#UhradyZbyva~gt~0")` (sum, overdue sum, max days overdue)
   + last 3 `ReceivedOrders(Filter:"Firma_ID~eq~<C>#DatumVystaveni~gte~<today-365>")` as header template.
5. Company checks: `CinnostUkoncena = true` or `DatumUkonceniCinnosti` ≤ today → **blocking B8**. Credit:
   if `PouzivatKredit` and (open receivables + this order total) > `HodnotaKreditu` → W1 (or blocking, Settings).
   Overdue invoices older than N days (Settings, default 14) → W2 with list. Both are shown in the review header.
6. Contact person: REST `Person` by e-mail → `Osoba_ID` on the order (when the person exists); unknown person →
   optional `person_create` suggestion, never blocking.

---------------------------------------------------------------------------------------------------
## 6. Duplicate protection (all checked again at approval time)

| # | Check | Result |
|---|---|---|
| D1 | `ReceivedOrders(Filter:"Firma_ID~eq~<C>#Odkaz~eq~<customer PO>")` returns any record | **blocking B2** with link to the Money order |
| D2 | Local: same `Message-ID` or same attachment `sha256` already produced a created order | **blocking B2** |
| D3 | Local draft for the same company + PO in state ≠ rejected/superseded | merge into existing draft (no second card) |
| D4 | No PO number: same company, ≥ 80 % same article+qty pairs, created in last 14 days | warning W11 "Možná duplicita" with link |
| D5 | Idempotency: `ReceivedOrders(Filter:"Poznamka~sw~SMID:<draft_id>")` before create | if found → mark created, never create again |
`Odkaz` comparison is case-insensitive after trimming and removing spaces (normalize the same way when writing).
Max length of `Odkaz` **[PROBE]** — if the PO number is longer, keep full number in `Poznamka` and truncated in `Odkaz`.

---------------------------------------------------------------------------------------------------
## 7. Item matching (customer lines → articles)

Cascade per line; stop at the first hit; store `match_method` + `match_confidence` + top-3 `candidates`.

| # | Method | Data | Confidence | Auto-accept? |
|---|---|---|---|---|
| 0 | Line copied from our offer | `offer_items.article_id` | 1.00 | yes |
| 1 | Our code exact | `money_articles.kod_normalized` == normalized `customer_code` or `our_code_guess` | 1.00 | yes |
| 2 | Customer code learned in Smart Mail | `customer_item_mappings (company_id, code_norm)` | 0.99 | yes |
| 3 | Customer code from Money history | `PartnerskyKod` on items of this customer's earlier `ReceivedOrders`/`IssuedInvoices` (`money_price_history.partner_code`) — only if one article was used for that code; several → candidates | 0.98 | yes |
| 4 | EAN | `money_articles.carovy_kod` == `ean` | 0.98 | yes |
| 5 | Catalog | `Katalog` exact (normalized) | 0.95 | yes |
| 6 | Customer's purchase history by text | trigram similarity of `text` vs names of articles this customer bought in 24 months ≥ 0.8 **and** attributes equal | 0.85–0.9 | no (amber) |
| 7 | Fastener attributes | deterministic parser (AI_ASSISTANT §8) → norm, d, length, material/strength, finish → `Articles.Parametry`/`Nazev` | 0.6–0.85 | no (amber) |
| 8 | Not found | user search, "Neskladová položka" (text line), or "Opýtať sa zákazníka" | — | — |

Code normalization (`normalize_code`): upper-case, strip, remove spaces, `-`, `.`, `/`, `_`; keep leading zeros but
also try without them; never fuzzy-match codes (no Levenshtein on codes — wrong article risk).

Hard safety rules (unit-tested):
- A candidate whose **critical attributes** differ from the parsed text (norm group, thread/diameter, length,
  material or strength class, finish/coating, head/drive when stated) is never auto-accepted, whatever the score; the
  differing attribute is highlighted in red in the candidate list ("A2 ≠ A4").
- **Norm equivalents** (DIN 933 ↔ ISO 4017, DIN 934 ↔ ISO 4032, … table in Settings) → status "Ekvivalent" (amber)
  unless `customer_order_templates.accepts_equivalents = true`.
- Inactive article (`Hidden`/`Deleted` = true, or `ProdejniCeny.Neaktivni` = true) is never proposed; if a learned
  mapping points to it → amber + alternatives from `ArticleAlternatives`.
- Matching runs in the bridge (`POST /orders/match`) against the cache + live checks; the main app never queries Money
  directly.
- Each user confirmation (or correction) writes/updates `customer_item_mappings` (company, code_norm, article, unit
  factor, confirmed_by, at, uses_count). Corrections of a previously learned mapping require a confirmation dialog
  ("Doteraz sme kód 4711 párovali na … Zmeniť?").

---------------------------------------------------------------------------------------------------
## 8. Quantities, prices, warehouse, header

### 8.1 Quantities and units
- Target unit = article sales unit (`Article.ProdejniJednotka`), conversion via `ArticleUnits` (`Mnozstvi` ratio to
  main unit). Example: customer "5 bal" of an article sold in ks with package 200 ks → 1 000 ks. Unknown package size
  → amber, the user enters the factor (saved to the mapping).
- **No packaging rounding (D6):** the quantity is written exactly as the customer ordered it (after unit
  conversion). Mandatory multiples, minimum order and `NedelitelneMnozstvi` are not checked and not shown.
- All quantities `Decimal`, compared with exact equality after quantize to 3 decimals.
- Allowed decimals per unit from `ArticleUnits.DesetinnaMista` (ks → 0): a non-integer quantity in a 0-decimal unit
  is blocking B4 (e.g. "2,5 ks" after a wrong price/qty column swap).

### 8.2 Prices
Source priority (Settings, default shown):
1. **Price from our accepted offer** (if within validity) — `price_source = offer`.
2. **Customer price from Money** `ProdejniCeny(FirmaID:<C>, SkladID:<branch warehouse>, MenaID:<M>, Filter:"Artikl_ID~eq~<A>")`
   (branch price list from SETTINGS_SPEC 11e goes to `ObsahPolozky.Cenik_ID`) →
   `CenaBezDanePoSleve` (unit price after customer discount), plus `Cenik_ID`, `Hladina_ID`, `Sleva`, `TypCeny`,
   `MnozstevniSleva`, `Zaokrouhleni` for audit — `price_source = price_list`.
3. Manual price by the user (role sales/admin, reason required) — `price_source = manual`.
The last price sold to this customer (history) is shown as information only.

Rules:
- Unit price stored with 4 decimals (fasteners cost fractions of a cent per piece); line totals computed for display
  only — **Money computes the document totals**; after create we read back and compare (§9.4).
- `MnozstevniSleva` not empty → warning W15 "Artikel má množstevnú zľavu" (the format of that string is
  **[PROBE]**); until the probe documents it, Smart Mail does not try to apply quantity discounts itself and the user
  confirms the price.
- Customer states a price (`lines[].price`) and it differs from ours by more than the tolerance (Settings, default
  0,5 % or 0,0005 €/ks) → warning W3 on the line with both values and buttons "Naša cena" (default) /
  "Cena zákazníka" (needs reason) / "Opýtať sa zákazníka".
- Currency of the order = company currency (`Mena_ID`); PO in another currency → blocking B6 until the user decides.
- Zero price on a stock line → blocking B5 unless the user marks it "Vzorka zdarma" (reason).
- VAT: the item rate comes from the article (`SazbaDPH_ID` / `DruhSazbyDPH` as in the customer's last order for the
  same article, else article default). EU customers with IČ DPH outside SK: header VAT mode copied from the customer's
  last order (template); no template → blocking B13 "Nastavte režim DPH" (we do not guess VAT modes).

### 8.3 Warehouse and delivery (no stock handling, D6)
- Every stock line gets the **branch warehouse** (SETTINGS_SPEC 11e: 10 Trnava, 20 Senica, 30 Nitra, 40 Trenčín) in
  `ObsahPolozky.Sklad_ID` — only because Money needs a warehouse on a stock item. A per-customer default warehouse
  (template) may override it.
- No `WarehouseStocks` query, no availability status, no shortage decisions, no reservation (`Rezervovano` is never
  sent). Delivery and stock are handled by people in Money as today.
- The requested delivery date / text from the PO is stored and written as described in §8.4; no feasibility check.

### 8.4 Header defaults
| Field (`ReceivedOrderInput`) | Value |
|---|---|
| `Firma_ID` | matched company |
| `Osoba_ID` | contact person (REST Person GUID) if known |
| `Odkaz` | customer PO number (normalized, §6) |
| `DatumVystaveni` | date the e-mail was received (Europe/Bratislava) |
| `CiselnaRada_ID` | Settings › Objednávky (codebook select) |
| `Mena_ID` | company currency |
| `ZpusobPlatby_ID` | company default; PO asks for another → W9, user decides |
| `ZpusobDopravy_ID` | mapping table text → `TransportTypes` (Settings), else company default; unknown text → W19 |
| `DodaciAdresaNazev/Ulice/Misto/PSC/Stat`, `DodaciAdresaFirma_ID` | from PO if it differs from the company's `Prov*`/`Obch*` address (W8 "Iná dodacia adresa"); else empty (Money uses the card) |
| `FakturacniAdresa*` | never from the PO automatically; different billing address on PO → W20, user decides |
| `Stredisko_ID` | **branch centre** (SETTINGS_SPEC 11e) — also on every item |
| `Zakazka_ID`, `Cinnost_ID` | Settings / customer template |
| `Obchodnik_ID` | Money staff GUID mapped to the approving user (Settings › Používatelia) **[PROBE type of ID]** |
| `Poznamka` | `SMID:<draft_id> · Smart Mail · e-mail <date> <sender>` + internal notes (always starts with SMID) |
| `TextPredCenami` | customer instructions that should print on documents (certificates 3.1, packaging, labels) — only when Settings "Tlačiť pokyny zákazníka" = on |
| `ZobrazitPoznamkuPriVyrizeni` | `true` when there are special instructions (warehouse sees them while fulfilling) |
| requested delivery date | **[PROBE / implementer: which field = "požadovaný termín dodania"]**; until confirmed → text in `Poznamka` and `TextPredCenami` ("Požadovaný termín: 12. 11. 2026") |

Items (`ReceivedOrderItemInput`), in the order of the customer document:
`Poradi`, `Nazev` (article name from Money, not customer text), `Katalog`, `Mnozstvi`, `Jednotka` (unit text of the
sales unit), `JednCena` (unit price excl. VAT, 4 dp), `Sleva: 0`, `TypCeny` **[PROBE enum for "bez DPH"; copy from the
customer's last order item]**, `SazbaDPH_ID`, `Poznamka` (customer text if it differs, requested date per line,
substitution note), `ObsahPolozky: { Artikl_ID, Sklad_ID, Mnozstvi, Jednotka_ID, Cenik_ID, CenovaHladina_ID,
PartnerskyKod: <customer code>, PartnerskyNazev: <customer text, max 100 chars> }`.
Non-stock text line: item without `ObsahPolozky` **[PROBE that Money accepts it; else block text lines]**.
Shipping: if Settings "Doprava ako položka" is on and the order total is below the free-shipping threshold and transport
is a paid type → add the configured service article line (amber, user can remove).

**Double discount guard [PROBE, blocking for go-live]:** create a TEST order for a customer with `HodnotaSlevy` > 0 with
explicit `JednCena` and `Sleva: 0` and read it back. If Money re-applies the customer discount, switch to the documented
alternative (send `JednotkovaCenaBezSlevy` = `CenaBezDane`, `Sleva` = `ProdejniCeny.Sleva`) — both variants are
implemented behind `ORDER_PRICE_MODE = explicit_net | base_plus_discount`, chosen by the probe result.

---------------------------------------------------------------------------------------------------
## 9. Writing to Money

### 9.1 Preconditions (re-evaluated server-side on approve; any failure → HTTP 409 with rule ids)
All B-rules green, draft `version` equals the version the user saw, payload hash equals the approval token hash,
bridge healthy, role allowed, Money agenda label matches Settings (TEST vs PROD banner shown in the card).

### 9.2 Call
`POST /orders/received` (bridge, approval JWT) →
```graphql
mutation($o: ReceivedOrderInput!) {
  CreateReceivedOrder(ReceivedOrder: $o) {
    ID CisloDokladu Odkaz SumaZaklad SumaDan SumaCelkem Mena_ID
    Polozky { ID Poradi Mnozstvi JednCena Sleva ObsahPolozky { Artikl_ID Sklad_ID } }
  }
}
```

### 9.3 State machine of `order_drafts.status`
```
draft ─(extraction done)→ needs_input ─(all B-rules green)→ ready
ready ─(approve)→ creating ─(Money ok + read-back ok)→ created ─(confirmation sent)→ confirmed
creating ─(Money error)→ failed ─(user retries after fix)→ ready
creating ─(timeout/unknown)→ unknown ─(reconcile by SMID)→ created | failed
any non-final ─(reject)→ rejected      created ─(undo within 15 min)→ undone
needs_input|ready ─(newer e-mail for same PO)→ superseded (new draft links to old)
```
Transitions are done in one DB transaction with `SELECT … FOR UPDATE` on the draft; `creating` is entered only once
per draft (unique `idempotency_key = SMID:<draft_id>`); a second approve while `creating` returns 409 "Objednávka sa
práve vytvára".

### 9.4 Read-back and compare
After success: `ReceivedOrder(ID:"<id>")` with items → compare count of items, `Artikl_ID`, `Mnozstvi` (exact),
`JednCena` (exact to 4 dp), and our computed net total vs `SumaZaklad` (± 0,01). Mismatch → status `created` with red
banner "Money upravilo objednávku" + diff table + actions "Otvoriť v Money" / "Vrátiť (zmazať)" (§9.6).

### 9.5 Errors (never auto-retry a mutation)
| Situation | Behaviour |
|---|---|
| GraphQL `errors[]` with validation message | status `failed`, message shown in Slovak + raw text in details, draft stays editable |
| 401 | refresh token once, then repeat **only the reconciliation query**, not the mutation |
| Timeout / connection reset after sending | status `unknown`; reconcile `ReceivedOrders(Filter:"Poznamka~sw~SMID:<id>")` after 30 s, 2 min, 10 min |
| Bridge offline | approve button disabled with "Money je nedostupné", draft stays `ready`, notification when back |

### 9.6 Undo
Within 15 min after create, role sales/admin, only if the order has no linked documents (no delivery note/invoice:
check `IssuedDeliveryNotes` items with `ZdrojovaPolozkaKopirovani_ID` pointing to its items **[PROBE]**) →
`DeleteReceivedOrder`. Audit logged. After 15 min → "Upravte v Money".

---------------------------------------------------------------------------------------------------
## 10. Order confirmation e-mail ("Potvrdenie objednávky")

Created automatically as a **draft suggestion** (type `order_confirmation`) right after `created`. Never sent without
approval. Settings per customer: send yes/no, language (customer's language), recipients (sender + PO contact; only
addresses of the same company — recipient check like invoices), attach PDF yes/no.

Content (template per language SK/CZ/EN/DE, editable in Settings › Objednávky):
1. Thanks + our order number `CisloDokladu` + customer PO `Odkaz`.
2. Table: customer code · our article name · quantity · unit price · line total.
3. **Changes vs. the request highlighted** (dropped lines, price differences, unit conversions) — generated from the
   draft diff, never written by the LLM from memory. No availability or delivery promises (D6).
4. Delivery method and address, payment terms (company `SplatnostPohledavek`), total excl./incl. VAT (from Money
   read-back), customer instructions acknowledged.
5. Signature of the approving user.
PDF (optional): "Potvrdenie objednávky č. {Money číslo}" rendered by Smart Mail from the read-back data with the shared
Money print template `templates/print/document.html.j2` (kind `order_confirmation`, layout of the Money report
"Ponuka vystavená" — DOCUMENTS_SPEC §5, fixture `fixtures/documents/order_confirmation_sample.json`) — Money has no
report endpoint for `ReceivedOrder` in the REST swagger.
Unknown lines (status `needs_input` for more than Settings hours) → AI prepares a **clarification e-mail**
("Pri položke 4 – 'skrutky M8 pozink' – potrebujeme dĺžku…") instead of a confirmation.
After send: REST Activity "Potvrdenie objednávky odoslané" linked to the company.

---------------------------------------------------------------------------------------------------
## 11. Changes and cancellations

- Detection: `order_change` / `order_cancel` with a reference (customer PO or our `CisloDokladu`) →
  `ReceivedOrders(Filter:"Firma_ID~eq~<C>#Odkaz~eq~<PO>")` or `…CisloDokladu~eq~<n>`.
- Card "Zmena objednávky": current Money order (items with `MnozstviVyrizeno`, `MnozstviZbyva`) vs requested change →
  diff (added / removed / quantity changed lines), with the same matching/price logic for new lines.
- **Smart Mail does not edit the Money order** (`EditReceivedOrder` replaces all items and would break partially
  fulfilled orders). It shows the diff, creates an internal task for the assigned user ("Upraviť objednávku OP… v
  Money"), and prepares the reply to the customer (accepted / partially possible / already shipped).
- Order not yet fulfilled and the change only adds lines → option "Vytvoriť doplnkovú objednávku" (new order with
  `Odkaz` = `<PO>-D1`) as an alternative.
- Cancellation: if any `MnozstviVyrizeno > 0` → reply draft "časť už bola odoslaná"; otherwise task "Stornovať v Money"
  + reply draft. Never `DeleteReceivedOrder` outside the 15-minute undo.

---------------------------------------------------------------------------------------------------
## 12. Status tracking

- Job every 30 min for drafts in `created|confirmed` younger than 60 days: `ReceivedOrder(ID)` →
  `Stav`, `Vyrizeno`, `PriznakVyrizeno`, `Storno`, items `MnozstviVyrizeno`, `MnozstviZbyva`; and delivery notes
  `IssuedDeliveryNotes(Filter:"Firma_ID~eq~<C>#DatumVystaveni~gte~<created>")` with items linked by
  `ZdrojovaPolozkaKopirovani_ID` **[PROBE]**.
- Display status (computed in code, not from guessed enum values): `Prijatá` (nothing fulfilled),
  `Čiastočne vybavená` (some `MnozstviVyrizeno` > 0), `Vybavená` (all `MnozstviZbyva` = 0 or `PriznakVyrizeno`),
  `Stornovaná` (`Storno` ≠ 0 **[PROBE meaning]**). Raw `Stav`/`Vyrizeno` values are stored and shown in details
  until their meaning is confirmed.
- On transition to `Čiastočne vybavená`/`Vybavená` with a new delivery note: optional suggestion "Tovar odoslaný"
  (reply in the original thread with delivery note number, carrier, tracking number found in carrier e-mails).
- Thread chip shows the status; Doklady › Objednávky lists all.

---------------------------------------------------------------------------------------------------
## 13. Validation rules (ids used in code, tests, UI and logs)

Blocking (primary button disabled, reason listed):
| Id | Rule |
|---|---|
| B1 | Company not selected / not confirmed |
| B2 | Duplicate: same customer PO already in Money (D1) or e-mail/attachment already created an order (D2) |
| B3 | A line without decision: unmatched article or amber match not confirmed |
| B4 | Quantity missing, ≤ 0 or not a valid decimal |
| B5 | Price missing or 0 on a stock line (unless "Vzorka zdarma" with reason) |
| B6 | Currency on PO ≠ company currency, not resolved |
| B7 | Confirmation recipient not belonging to the company (applies to the confirmation e-mail) |
| B8 | Company inactive (`CinnostUkoncena` / `DatumUkonceniCinnosti`) |
| B9 | Draft changed after the approval token was issued (hash/version mismatch) |
| B10 | Article inactive or deleted in Money (re-checked live at approval) |
| B11 | Money bridge unavailable / agenda label mismatch |
| B12 | Sender's company ≠ company on PO, not resolved |
| B13 | Foreign EU customer without VAT template |
| B14 | Credit limit exceeded when Settings "Kontrola kreditu" = block |
| B15 | Branch of the order has no stredisko / cenník / sklad set (SETTINGS_SPEC 11e) |

Warnings (amber, must be acknowledged by a click; acknowledgement stored per draft):
W1 credit limit exceeded · W2 overdue invoices · W3 customer price ≠ our price · W4 *(removed in v2.6, D6)* ·
W5 *(removed in v2.6, D6)* · W6 norm equivalent used · W7 *(removed in v2.6, D6)* · W8 different
delivery address · W9 different payment type · W10 below free-shipping threshold · W11 possible duplicate without PO ·
W12 customer's stated total ≠ our total (> 0,5 %) · W13 PO older than 30 days · W14 offer expired · W15 quantity discount
on article · W16 ambiguous number format · W17 unknown unit · W18 possibly missing line · W19 unknown transport text ·
W20 different billing address on PO.

---------------------------------------------------------------------------------------------------
## 14. Data model (main app; Alembic migration in Phase 4)

`order_drafts`: id (uuid), thread_id, message_id, source_kind (body|pdf|scan|xlsx|csv|docx|xml|offer),
source_attachment_id, company_id, person_id, company_match_method, customer_po, customer_po_norm, po_date,
currency, payment_type_id, transport_type_id, delivery_address (jsonb), billing_address_on_po (jsonb),
requested_date, requested_text, customer_notes, internal_notes, print_instructions (bool), offer_id,
status (enum §9.3), version (int, optimistic lock), idempotency_key (unique), money_order_id, money_order_number,
money_status_raw (jsonb), display_status, totals_ours (jsonb), totals_money (jsonb), readback_diff (jsonb),
checks (jsonb: rule id → result), acknowledgements (jsonb: rule id → user, at), created_by_ai_run_id, approved_by,
approved_at, created_at, updated_at, superseded_by.
Unique partial index: (company_id, customer_po_norm) where status not in (rejected, superseded, undone).

`order_draft_lines`: id, draft_id, line_no, source (jsonb), raw_text, customer_code, customer_code_norm, ean,
attributes (jsonb), customer_qty (numeric(18,3)), customer_unit_text, customer_price (numeric(18,6)), price_per,
article_id, match_method, match_confidence, candidates (jsonb), unit_id, unit_factor (numeric(18,6)),
qty (numeric(18,3)), unit_price (numeric(18,4)), price_source (offer|price_list|manual),
price_meta (jsonb: Cenik_ID, Hladina_ID, Sleva, TypCeny, MnozstevniSleva), price_reason, warehouse_id,
decision (accept|drop|text_item), vat_rate_id, note, line_status (matched|confirm|unmatched|text|dropped), confirmed_by,
confirmed_at.

`customer_item_mappings`: company_id, code_norm, article_id, unit_factor, confirmed_by, confirmed_at, uses_count,
last_used_at; unique (company_id, code_norm).

`customer_order_templates`: company_id (pk), column_map (jsonb), default_warehouse_id, transport_type_id,
accepts_equivalents (bool), send_confirmation (bool),
confirmation_language, confirmation_recipients (text[]), attach_pdf (bool), vat_template (jsonb), updated_by.

All money/quantity columns are `numeric`; Python uses `Decimal` end-to-end; JSON serialises decimals as strings.

---------------------------------------------------------------------------------------------------
## 15. API (main app) and bridge endpoints

Main app (all require auth; writes require role and CSRF):
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/orders?status=&company=&q=` | Doklady › Objednávky list |
| GET | `/api/orders/{id}` | draft with lines, checks, company context |
| PATCH | `/api/orders/{id}` (If-Match: version) | header edits |
| PATCH | `/api/orders/{id}/lines/{line_id}` (If-Match) | article / qty / price / warehouse / decision |
| POST | `/api/orders/{id}/lines` · DELETE `/api/orders/{id}/lines/{line_id}` | add / remove line (user) |
| POST | `/api/orders/{id}/lines/{line_id}/split` | split across warehouses |
| POST | `/api/orders/{id}/acknowledge` {rule_ids[]} | acknowledge warnings |
| POST | `/api/orders/{id}/approve` | → approval token → bridge create → read-back |
| POST | `/api/orders/{id}/undo` | within 15 min |
| POST | `/api/orders/{id}/reject` {reason} | |
| POST | `/api/orders/{id}/clarification` | draft clarification e-mail |
| GET | `/api/orders/{id}/source` | original document + highlight boxes |

Bridge (HMAC; create needs approval JWT):
| Method | Path | Money |
|---|---|---|
| POST | `/orders/match` {company_id, lines[]} | cascade §7 on cache + live checks |
| GET | `/customers/{id}/order-context` | §5.4 company fields, receivables summary, last orders (template) |
| GET | `/orders/received/duplicates?company_id=&po=` | D1 |
| GET | `/orders/received/by-smid/{smid}` | D5 / reconciliation |
| POST | `/orders/received` | `CreateReceivedOrder` + read-back |
| GET | `/orders/received/{id}` | status §12 |
| GET | `/orders/received/{id}/deliveries` | delivery notes linked to the order |
| DELETE | `/orders/received/{id}` | undo (approval JWT, 15 min, no linked documents) |
| GET | `/prices?company_id=&warehouse_id=&currency_id=&article_ids=` | §8.2 |

---------------------------------------------------------------------------------------------------
## 16. Settings › Objednávky (admin) and per-customer template

Admin: číselná rada (codebook; branch series from 11e win), zákazka / činnosť, mapovanie používateľ → obchodník v
Money, tolerancia ceny zákazníka (%, €/ks), kontrola kreditu (vypnutá / upozorniť / blokovať), hranica po splatnosti
(dni), akceptovať normové ekvivalenty (predvolene nie), mapovanie textu
dopravy → spôsob dopravy, doprava ako položka (artikel, hranica), tlačiť pokyny zákazníka (TextPredCenami),
šablóny potvrdenia SK/CZ/EN/DE, PDF potvrdenia áno/nie, automaticky pripraviť potvrdenie po vytvorení (áno),
ignorovať odosielateľov (e-shop), hodiny do upozornenia na nevyriešenú objednávku, režim ceny `ORDER_PRICE_MODE`
(len správca, podľa testu). Sklad = sklad pobočky (11e); zásoby, rezervácia a balenia sa neriešia (D6).
Per customer (Kontakty › firma › Objednávky): mapovanie stĺpcov, sklad, doprava, ekvivalenty,
potvrdenie (áno/nie, jazyk, príjemcovia, PDF), naučené kódy zákazníka (tabuľka, úprava, export CSV).

---------------------------------------------------------------------------------------------------
## 17. AI responsibilities and limits

- AI: classification, extraction from free text/PDF/scan, proposing column mapping, attribute parsing help, writing
  the human text of confirmation/clarification e-mails (tables and numbers are inserted by code from data).
- Code (never AI): numbers, units, prices, totals, duplicates, matching decisions for codes,
  validation rules, Money payloads.
- The LLM never sees Money credentials and never produces GraphQL; it fills the extraction schema only.
- Prompts: `app/ai/prompts/extract_order.md` (schema + rules of §4.2 + 3 few-shot examples: SK body text,
  DE PDF with "Preis/100", XLSX with customer codes) and `order_confirmation.md`.

---------------------------------------------------------------------------------------------------
## 18. Tests (part of Phase 4 definition of done)

Fixtures in `tests/fixtures/orders/` (anonymised real documents, ≥ 25): plain text SK; HTML table; PDF text; scanned
PDF; photo of a printed order; XLSX with customer codes; CSV `;` separated with `1 000,50`; DE PDF with `Preis/100` and
`1.000`; EN with `1,000.50`; reply accepting offer; PO with different delivery address; PO with unknown items; PO with
quantity not matching packaging (must be written unchanged); PO in CZK for EUR customer; two POs in one e-mail; forwarded by colleague; order change;
cancellation; e-shop notification (must be ignored); duplicate re-sent PO; PO with total line and shipping line.
Each fixture has `expected.json` (header + lines + expected match methods + expected B/W rule ids).

Unit tests: `parse_decimal` (all locales, ambiguous), unit/price_per conversion, `normalize_code`,
critical-attribute guard, equivalents, cascade order, duplicate rules D1–D5, state machine (all allowed and forbidden
transitions), validation rules B1–B15 and W1–W20 (W4, W5, W7 removed), confirmation diff generator, filter builder for `Odkaz` values with
unsafe characters.
Integration (mock bridge): approve → create → read-back ok; read-back mismatch; GraphQL error; timeout → `unknown` →
reconciliation finds the order (no second create); double click approve (second gets 409); undo within/after 15 min.
E2E (Playwright, desktop + mobile): PDF order → review → resolve amber line → create → confirmation draft → send.
AI eval: extraction accuracy per field on fixtures (target: quantity 100 %, codes ≥ 98 %, lines count 100 %).

Acceptance on TEST agenda (Phase 4): 20 real orders from 10 customers → 0 wrong quantities or prices in Money
(prices equal `ProdejniCeny` or the accepted offer), 0 duplicates, read-back equal in 100 %, ≥ 90 % lines matched
automatically for customers with a previous order, median time from opening the card to created order < 60 s.

Shadow mode rollout (CLAUDE.md §0.1): for the first 2 weeks after Phase 4 the create button is hidden for orders;
drafts are still produced. Nightly job `orders_shadow_compare` finds orders people created manually in Money for the
same customer + `Odkaz` (or same customer, same day, ≥ 80 % same articles) and stores per-line comparison (article,
quantity, unit price, warehouse). Admin › Objednávky – presnosť shows the report; the feature flag `orders_create`
is switched on only when ≥ 95 % of lines are identical and no wrong price/quantity was found in the last 5 working days.

---------------------------------------------------------------------------------------------------
## 19. Probe items for orders (`tools/money_probe.py --orders`, TEST agenda only)
Read-only part: list last 20 `ReceivedOrders` with all header fields used here and items (`ObsahPolozky`,
`PartnerskyKod`, `TypCeny`, `Sleva`), distinct values of `Stav`, `Vyrizeno`, `Storno`, `Faze`;
`ProdejniCeny` sample incl. `MnozstevniSleva` strings; `TransportTypes`, `PaymentTypes`; `IssuedDeliveryNotes` items
with `ZdrojovaPolozkaKopirovani_ID` resolvable to order items.
Write part (only with `--allow-write-test` and agenda label TEST, prints a warning and asks for "TEST" typed):
create one order for a test customer with discount → read back (double discount guard),
text line without `ObsahPolozky`, long `Odkaz`, then `DeleteReceivedOrder`. Results go to `probe_output/orders.md`.

---------------------------------------------------------------------------------------------------
## 20. Questions for the Money implementer (orders)
1. Which field of Objednávka prijatá is "Požadovaný termín dodania" (header and item)? Is `DatumVyrizeni` that field?
2. Does `CreateReceivedOrder` reserve stock automatically? (Smart Mail does not handle stock — D6; we only need to know
   whether Money reserves by itself.)
3. If we send `JednCena` with `Sleva: 0`, can Money re-apply the customer discount or price list? Recommended way to
   send customer prices via API?
4. Meaning of `Stav`, `Vyrizeno`, `Storno`, `Faze`, `TypCeny` values for orders.
5. Are item text lines (without article) allowed on received orders via API?
6. Is the link delivery note item → order item available via `ZdrojovaPolozkaKopirovani_ID`?
7. Max length of `Odkaz`; is `Odkaz` printed on the delivery note and invoice (customers need their PO there)?
8. ~~Do e-shop orders arrive in Money?~~ Answered: yes, directly (D6).
9. Is there a print report for Objednávka prijatá / Potvrdenie objednávky available via REST (to use Money's PDF)?
