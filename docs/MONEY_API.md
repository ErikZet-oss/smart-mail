# MONEY_API.md — Money S4 integration (v2.8: GraphQL first, REST where needed)

Sources of truth (copy them into the repo, never edit):
- `bridge/schema/graphql_schema.json` — introspection of the customer's server (`GET {base}/graphql/schema`),
  135 types, 117 queries, 87 mutations. Generate typed models from it.
- `bridge/schema/swagger_v1.json`, `bridge/schema/swagger_v2.json` — REST API (S5Api v1.0 / v2.0).
- Official docs: https://docs.moneyerp.com/developer (GraphQL), token: /developer/autorizace,
  requests: /developer/posilani-requestu, filters: /developer/filtrovani.
- `probe_output/report.md` — results of `tools/money_probe.py` on the TEST agenda (answers items marked **[PROBE]**);
  `probe_output/orders.md` — results of `money_probe.py --orders` (customer orders, see `docs/ORDERS_SPEC.md` §19);
  `probe_output/branches.md` — results of `money_probe.py --branches` (codebooks for branch dropdowns + analysis of
  received delivery notes, see `docs/DOCUMENTS_SPEC.md` §8).
- `docs/ORDERS_SPEC.md` — complete specification of customer orders (this file only lists the Money calls).
- `docs/DOCUMENTS_SPEC.md` — Money-identical documents: received delivery note card and field mapping, offer and order
  confirmation PDF (copy of the Money print report), invoice PDFs only from Money, numbering.
Never call the PRODUCTION agenda without explicit approval from the user in chat.

---------------------------------------------------------------------------------------------------
## 1. Which API for what

| Need | API | Why |
|---|---|---|
| Almost everything (read + write documents, address book, catalog, stock, prices, codebooks) | **GraphQL** `POST {base}/graphql` | covers delivery notes, stock, supplier codes, customer prices; items accept `ObsahPolozky { Artikl_ID, Sklad_ID }` |
| PDF of a document | **REST** `GET /v2.0/{IssuedInvoice|PrepaymentIssuedInvoice|ReceivedInvoice|PrepaymentInvoice|PriceList|Service}/{id}/Report/{reportId}` | GraphQL has no report/PDF; delivery notes, orders and offers have no report at all (§5.9b) |
| Contact persons (`Person`), CRM activities (`Activity`, `TypeOfActivity`), staff (`Staff`) | **REST** | not in the customer's GraphQL schema |
| Proforma invoices (`PrepaymentIssuedInvoice`, `PrepaymentInvoice`) | **REST** | not in the customer's GraphQL schema |
| Offers (Nabídka vydaná / `IssuedOffer`) | **GraphQL once added** — not on the server yet | Smart s.r.o. arranges it with the implementer (DECISIONS D5); offers are created in Money and numbered by Money (§5.7) |

Authentication (same token for both): `POST {base}/connect/token`,
`Content-Type: application/x-www-form-urlencoded`,
`grant_type=client_credentials&client_id=…&client_secret=…&scope=S5Api` → `Authorization: Bearer <access_token>`.
Cache the token until `expires_in − 60 s`, single-flight refresh, retry once on 401.

---------------------------------------------------------------------------------------------------
## 2. GraphQL conventions (customer's schema)

- Request: `POST /graphql` with JSON `{"query": "...", "variables": {...}}`. Schema: `GET /graphql/schema` (no auth).
- Field names are **PascalCase** (`CisloDokladu`, `Firma_ID`, `UhradyZbyva`). IDs are GUID strings.
- List queries (plural name) take `Filter: String, From: Int, Count: Int, ChangeFrom: DateTime`.
  Single queries (singular name, e.g. `Company(ID: "…")`) take only `ID`.
  There is **no `Order` argument** on this server → sort client-side; for "latest" fetch a bounded date range.
- Filter syntax: `Field~op~value`; AND = `#`, OR = `|`, parentheses group:
  `"(Misto~eq~Brno#Nazev~eq~Seyfor)|(ICO~eq~60737691)"`.
  Operators: text `eq ne sw ct ew`; numbers/dates `eq ne lt lte gt gte`; bool `eq ne`.
  Only root fields can be filtered (not nested lists like `SeznamSpojeni`). Value escaping of `~ # | ( )` is
  undocumented **[PROBE]** — reject or strip these characters in user-provided values. Date format **[PROBE]**
  (use `YYYY-MM-DD`). Default page limit 1000 (server `config.json`) — always page with `From`/`Count` ≤ 500.
- `ChangeFrom: DateTime` returns records changed since — use it for delta sync of the read cache.
- Mutations: `Create<Entity>(<Entity>: <Entity>Input!)`, `Edit<Entity>(...)`, `Delete<Entity>(...)`, return the entity
  (request `ID CisloDokladu` back). Child records are arrays in the input (`Polozky: [...]`).
  **Editing a document replaces ALL its items** (official doc) → Smart Mail only creates documents, never edits them.
- Item ↔ article/warehouse link: `ObsahPolozky: ContentOfItemWithArticleInput { Artikl_ID, Sklad_ID, Mnozstvi,
  Jednotka_ID, Cenik_ID, CenovaHladina_ID, PartnerskyKod, PartnerskyNazev, Zasoba_ID }`.
- Generate a typed client from the schema (e.g. `ariadne-codegen` or hand-written Pydantic models for the ~25 types
  used). Keep query strings in `bridge/app/queries/*.graphql`.
- Idempotency: put `SMID:<suggestion_id>` at the start of `Poznamka`; before any Create, query
  `<Entities>(Filter:"Poznamka~sw~SMID:<id>")`. Never auto-retry a mutation.

---------------------------------------------------------------------------------------------------
## 3. Entities used (GraphQL unless marked REST)

| Query (list) / mutation | Money (SK) | Use in Smart Mail | R/W |
|---|---|---|---|
| `IssuedInvoices` | Faktúra vydaná | find invoice, payment status (`UhradyZbyva`, `DatumUhrady`, `KUhrade`), reminders, last sold prices from `Polozky` | R |
| REST `PrepaymentIssuedInvoice` | Zálohová faktúra vydaná | proforma requests | R |
| `ReceivedInvoices` | Faktúra prijatá | read only (optional: open purchase context); **never created** (DECISIONS D7) | R |
| `ReceivedDeliveryNotes` / `CreateReceivedDeliveryNote` | **Dodací list prijatý** | goods receipt with articles + warehouse | R/W |
| `IssuedOrders` | Objednávka vydaná | open purchase orders → expected quantities/prices (`MnozstviZbyva`) | R |
| `ReceivedOrders` / `CreateReceivedOrder` | Objednávka prijatá | order from e-mail, order status | R/W |
| `IssuedDeliveryNotes` | Dodací list vydaný | "kedy príde tovar" – shipped? (`Stav`, `DatumSkladovehoPohybu`, `ZpusobDopravy`) | R |
| `ReceivedComplaints` / `CreateReceivedComplaint` | **Reklamácia prijatá** | complaint from e-mail with items | R/W |
| `Companies` / `CreateCompany` | Firma | matching, customer card (`Email`, `SeznamSpojeni`, `HodnotaSlevy`, `SplatnostPohledavek`, `SeznamCeniku`), new partner | R/W |
| REST `Person`, `Connection` | Osoba, Spojenie | contact persons by e-mail | R/W |
| `Articles` | Položka katalógu | `Kod`, `Katalog`, `CarovyKod`, `Nazev`, `ObchodniNazev`, `Parametry`, `Baleni`, `PovinnyNasobek`, `MinimalniObjednavka`, `PosledniCena`, `SeznamDodavatelu` | R |
| `ArticleSuppliers` | Dodávateľ položky katalógu | **supplier codes**: `Firma_ID`, `DodavatelskyKod`, `DodavatelskyNazev`, `PosledniCena`, `Jednotka`, `PovinnyNasobek`, `MinimalniObjednavka`, `Parent_ID` (= article **[PROBE]**) | R |
| `ArticleUnits` | Jednotky položky | unit conversion (`Mnozstvi`, `ParentJednotka`) | R |
| `ArticleAlternatives` | Alternatívy | substitutes in offers when out of stock | R |
| `WarehouseStocks` | Zásoba | `DostupneMnozstvi`, `Rezervovano`, `Objednano` per `Artikl_ID` + `Sklad_ID` | R |
| `ProdejniCeny(FirmaID!, SkladID, MenaID)` | Predajné ceny | **customer-specific price after discount** (`CenaBezDanePoSleve`, `CenaSDaniPoSleve`, `Sleva`, `HladinaNazev`) + stock (`ZustatekMnozstvi`) | R |
| `PriceLists`, `PriceListItems`, `CompanyPriceLists` | Cenníky | price list info, which lists apply to a company | R |
| `Warehouses`, `NumericalSeries`, `AccountAssignments`, `VATClassifications`, `VatRates`, `Currencies`, `PaymentTypes`, `TransportTypes`, `Units`, `Centres`, `JobOrders`, `Operations`, `Countries` | Číselníky | Settings selects (no GUID copying), validation | R |
| REST `Activity`, `TypeOfActivity`, `Staff` | Aktivity, zamestnanci | log e-mails, follow-up tasks, user mapping | R/W |
| REST `…/Report/{reportId}` | PDF | invoice/proforma/price list PDF | R |
| `Version` | — | health check, show API version in admin | R |

---------------------------------------------------------------------------------------------------
## 4. Read cache (main app DB, refreshed via bridge with `ChangeFrom`)

| Cache | Source | Refresh |
|---|---|---|
| `money_companies` (+ e-mails from `Email` and `SeznamSpojeni[].SpojeniCislo`) | `Companies` | 15 min delta (`ChangeFrom`), nightly full |
| `money_persons` | REST `Person` | 15 min |
| `money_articles` (+ `Parametry`, units, packaging) | `Articles` | 15 min delta |
| `money_article_suppliers` (supplier_id, supplier_code normalized, article_id, unit, last price, packaging) | `ArticleSuppliers` | 15 min delta |
| `money_price_history` (customer, article, qty, unit price, date, document, `partner_code` = `ObsahPolozky.PartnerskyKod`) | `IssuedInvoices.Polozky` + `ReceivedOrders.Polozky` | nightly (24 months) + after each created order |
| `money_codebooks` (all lists in §3 "Číselníky") | GraphQL | daily |
Stock and customer prices are always live (`WarehouseStocks`, `ProdejniCeny`) with a 60 s memo cache.

---------------------------------------------------------------------------------------------------
## 5. Use cases

### 5.1 Customer asks for an invoice copy
`IssuedInvoices(Filter:"CisloDokladu~eq~<n>", Count:5) { ID CisloDokladu VariabilniSymbol Firma_ID DatumVystaveni
DatumSplatnosti CelkovaCastka UhradyZbyva Mena_ID Odkaz TypDokladu }` → fallbacks `VariabilniSymbol~eq~`,
`Odkaz~eq~<customer PO>`, `Firma_ID~eq~<company>#DatumVystaveni~gte~<from>#DatumVystaveni~lte~<to>`, then
`CisloDokladu~ct~<digits>`. Proforma → REST `PrepaymentIssuedInvoice`.
**Blocking check:** `Firma_ID` == company of the recipient address. PDF: REST
`GET /v2.0/IssuedInvoice/{ID}/Report/{reportId}` (report per customer language from Settings). After approved send:
REST `POST /v1.0/Activity`.

### 5.2 Receivables, payment questions, reminders
`IssuedInvoices(Filter:"Firma_ID~eq~<X>#UhradyZbyva~gt~0")` (+ REST prepayments). Overdue = `DatumSplatnosti` < today.
Reminder e-mail with table + PDFs; log Activity "Upomienka odoslaná". Smart Mail does not edit reminder dates.

### 5.3 Customer card (panel "Zákazník")
`Company(ID:"<X>") { Nazev ICO DIC ICDPH Email HodnotaSlevy VlastniSleva SplatnostPohledavek
SeznamSpojeni { SpojeniCislo TypSpojeni { Kod } } SeznamCeniku { … } }` + receivables (5.2) + last `ReceivedOrders` and
`IssuedDeliveryNotes` of the company + REST Activities + REST Persons.

### 5.4 Sender → company matching
Cache lookup in this order: person e-mail (REST Person, `Parent_ID` = company **[PROBE]**) 0.98 → company
`SeznamSpojeni`/`Email` 0.95 → IČO from signature 0.9 → same non-free-mail domain 0.7 (confirm once) → confirmed
links table. Unknown → "Priradiť k firme / Založiť firmu" (`CreateCompany` + REST `POST Person`).

### 5.5 Supplier invoice / delivery note → items matched → Dodací list prijatý (core flow; no Faktúra prijatá, D7)

**5.5.1 Extraction** — header + all lines: supplier item code, EAN, description, quantity, unit, unit price, discount,
VAT rate, line total, customer PO reference, delivery note number. Sources: ISDOC/UBL XML attached to the e-mail
(deterministic), otherwise the LLM reads the PDF directly (text layer + tables; scans/images with OCR + vision) — no
`fa_pdf` (DECISIONS D3). Every value with confidence and page/bbox.

**5.5.2 Supplier** — `Companies(Filter:"ICO~eq~<ico>")` (then DIČ/IČ DPH/name). Unknown → `company_create` suggestion
first. Duplicates (blocking): `ReceivedDeliveryNotes(Filter:"Firma_ID~eq~<S>#Odkaz~eq~<supplier doc no>")` and
`ReceivedDeliveryNotes(Filter:"Poznamka~sw~SMID:<id>")`.

**5.5.3 Item matching cascade** (per line; stop at first hit; store method + confidence):
| # | Method | Query / data | Confidence |
|---|---|---|---|
| 1 | Supplier code in Money | `money_article_suppliers` where supplier = S and normalized `DodavatelskyKod` == normalized line code (remove spaces, dashes, dots, leading zeros variant) | 1.00 |
| 2 | Learned mapping (confirmed earlier in Smart Mail, not yet in Money) | `item_mappings` (supplier_id, code) | 0.99 |
| 3 | EAN | `Articles.CarovyKod` | 0.98 |
| 4 | Our code / catalog | `Articles.Kod` / `Katalog` == line code | 0.95 |
| 5 | Open purchase order | `IssuedOrders(Filter:"Firma_ID~eq~<S>")` items with `MnozstviZbyva > 0` whose `Katalog`/`Nazev` matches | 0.9 |
| 6 | Fastener attributes | parse norm (DIN/ISO + equivalents), size, length, strength/material, finish from text vs `Articles.Parametry` / `Nazev` | 0.6–0.85 (needs confirmation) |
| 7 | Not found | user picks article (search box) or marks "neskladová položka" (text item, no article) | — |
Each confirmation by a user stores the mapping (#2) so the same code is automatic next time.

**5.5.4 Units and packaging** — supplier unit (`ArticleSupplier.Jednotka`) vs article main unit (`HlavniJednotka`) via
`ArticleUnits` (`Mnozstvi` ratio): e.g. "1 bal (200 ks)" → 200 ks; price per unit converted accordingly.

**5.5.5 Checks per line** — price vs `ArticleSupplier.PosledniCena` (warn above ±X % setting, default 10 %);
quantity vs open purchase order remaining (`MnozstviZbyva`); VAT rate valid; sum of lines == document total (±0.01);
reverse charge consistency. Header checks: dates, currency. (No IBAN/payment checks — invoices are not imported, D7.)

**5.5.6 Warehouse** — the branch warehouse (SETTINGS 11e: 10 Trnava, 20 Senica, 30 Nitra, 40 Trenčín — D4, D11); the
user can pick any warehouse from the complete Money list (D18; a non-branch warehouse gives warning DL-W8). Price
lists come from `PriceLists` — all of them are offered in the dropdowns (D12, D18). Warehouses and price
lists are always loaded from Money — never hardcoded codes or GUIDs. Stock movement date/time = moment of the write
(D13); fees are not written (D14); no negative quantities (D15).

**5.5.7 Writing to Money** (after approval; role `warehouse`, `accounting` or `admin`). **Only
`CreateReceivedDeliveryNote`** (DECISIONS D7) with the complete field mapping of the Money card in **DOCUMENTS_SPEC §2**
(Doklad prijatý = `Odkaz`, Popis = `Nazev`, `ParovaciSymbol` = supplier invoice number, Vystavenie / Účt. prípadu /
Sklad. pohybu + čas, `Predkontace_ID`, `DruhPohybu_ID` "obstaranie" and `DruhSkladovehoPohybu_ID` "príjem" +
`RegistraceDPH_ID` + item `TypCeny` "Iba základ" + `DruhPolozky_ID` "tovar" copied from the branch template document,
branch `Stredisko_ID` on header and items, branch `Sklad_ID`, branch series; item `Nazev`/`Katalog` = Money article,
supplier code and text in `ObsahPolozky.PartnerskyKod` / `PartnerskyNazev`) → `{ ID CisloDokladu Polozky { ID
CisloPolozky Zbyva } }`. The received invoice is entered by people in Money as today; Smart Mail never calls
`CreateReceivedInvoice` or REST `PrepaymentInvoice`.
- After create: read back the document, compare lines and totals; mismatch → red banner + "Vrátiť"
  (`DeleteReceivedDeliveryNote`) within 15 min, only if not invoiced, audit logged.
- Original PDF/XML stays in Smart Mail document store; link in `Poznamka`.

**5.5.8 Supplier codes learned in Smart Mail** — the customer's schema has **no write access to supplier codes**
(`ArticleInput` has no `SeznamDodavatelu`, there is no `CreateArticleSupplier`). Confirmed matches are stored in the
local `item_mappings` table (supplier_id, normalized code, article_id, unit factor, confirmed_by, date) and shown in
Settings › Money S4 › Kódy dodávateľov with CSV export, so the accountant can also enter them into Money cards.
If the implementer enables supplier-code writes, add a bridge endpoint and sync the table to Money (admin setting).

### 5.5.9 Branch values on every write (PRODUCT_SPEC §2.0, SETTINGS_SPEC 11e)
Resolve the document's branch first, then: header `Stredisko_ID` = branch centre; every item `Stredisko_ID` = branch
centre; `ObsahPolozky.Sklad_ID` = branch warehouse (unless the user changed the line); `ObsahPolozky.Cenik_ID` = branch
price list; `CiselnaRada_ID` = branch series override or company default. Codebooks: `Centres { ID Kod Nazev }`,
`PriceLists { ID Kod Nazev VychoziSklad_ID }`, `Warehouses { ID Kod Nazev }`. **[PROBE]** verify on TEST that a received
delivery note created with these values shows the centre on the document and increases stock in the branch warehouse,
and whether `Cenik_ID` on received items is required or ignored (implementer question 8).

### 5.6 Customer order from e-mail → Objednávka prijatá (full spec: `docs/ORDERS_SPEC.md`)
Calls in order (all via bridge):
1. Customer context: `Company(ID){ … }` (fields in ORDERS_SPEC §5.4), receivables
   `IssuedInvoices(Filter:"Firma_ID~eq~<C>#UhradyZbyva~gt~0")`, last orders `ReceivedOrders(Filter:"Firma_ID~eq~<C>#
   DatumVystaveni~gte~<d>", Count:3)` as header/VAT template.
2. Duplicates: `ReceivedOrders(Filter:"Firma_ID~eq~<C>#Odkaz~eq~<PO>")` and `ReceivedOrders(Filter:"Poznamka~sw~SMID:<id>")`.
3. Matching cache: `money_articles`, `customer_item_mappings`, `money_price_history.partner_code`
   (`ObsahPolozky.PartnerskyKod` of earlier documents of the customer), `ArticleUnits` (`Mnozstvi`, `DesetinnaMista`,
   unit conversion only).
4. Prices: `ProdejniCeny(FirmaID:<C>, SkladID:<branch W>, MenaID:<M>, Filter:"Artikl_ID~eq~<A>")` →
   `CenaBezDanePoSleve`, `Cenik_ID`, `Hladina_ID`, `Sleva`, `TypCeny`, `MnozstevniSleva`, `Neaktivni`.
5. No stock query, no reservation, no packaging rounding (DECISIONS D6); items get the branch warehouse.
6. Create: `CreateReceivedOrder(ReceivedOrder:{ Firma_ID, Osoba_ID, Odkaz, DatumVystaveni, CiselnaRada_ID, Mena_ID,
   ZpusobPlatby_ID, ZpusobDopravy_ID, DodaciAdresa…, Stredisko_ID, Zakazka_ID, Cinnost_ID, Obchodnik_ID,
   Poznamka:"SMID:…", TextPredCenami, ZobrazitPoznamkuPriVyrizeni, Polozky:[{ Poradi, Nazev, Katalog, Mnozstvi,
   Jednotka, JednCena, Sleva:0, TypCeny, SazbaDPH_ID, Poznamka, ObsahPolozky:{ Artikl_ID, Sklad_ID, Mnozstvi,
   Jednotka_ID, Cenik_ID, CenovaHladina_ID, PartnerskyKod, PartnerskyNazev } }] })` → read-back `ReceivedOrder(ID)`.
   `ORDER_PRICE_MODE` (explicit_net | base_plus_discount) decided by the probe (double discount guard).
7. Undo: `DeleteReceivedOrder` within 15 min if no linked delivery note. Status: `ReceivedOrder(ID)` (`Stav`,
   `Vyrizeno`, `PriznakVyrizeno`, `Storno`, items `MnozstviVyrizeno`, `MnozstviZbyva`) + `IssuedDeliveryNotes`.
Never `EditReceivedOrder` (replaces all items). Confirmation PDF is rendered by Smart Mail (no REST report for
`ReceivedOrder` in the swagger).

### 5.7 Offers (DECISIONS D5)
Offers are **created in Money and numbered by Money**. `IssuedOffer` (Nabídka vydaná) is not on the server yet —
Smart s.r.o. arranges it with the implementer; `money_probe.py` reports "IssuedOffer (ponuky) in schema: True/False".
Until it is available the offers module (Phase 6) is not built. Flow: offer draft in Smart Mail (lines matched to
articles, prices `ProdejniCeny(FirmaID, SkladID = branch warehouse)` with source, stock `WarehouseStocks` as
information for all warehouses (D18), substitutes `ArticleAlternatives`, no packaging rounding — D17) → approval → `CreateIssuedOffer` (branch
`Stredisko_ID`, series of Settings 13c / branch override) → read-back with `CisloDokladu` → PDF: the Money report if
the implementer adds an offer report endpoint (question 11), otherwise `templates/print/` (DOCUMENTS_SPEC §4) with the
Money number → send after approval. Accepted → `CreateReceivedOrder` (ORDERS_SPEC §4.4).
**[PROBE when available]** the exact `IssuedOfferInput` fields — never guess them; validate the mutation with
`tools/validate_graphql.py` against the new schema.
Reference for the fields and query shapes: `docs/reference/money-s4-issued-offer.md` (its SQL path is not allowed for
Smart Mail, DECISIONS D28). Before Phase 6 the customer checks Money › Administrácia › Výmena dát › REST API (enabled
agendas); the list query may be named `IssuedOffers` on this server (plural, like `IssuedSalesDocs`).

### 5.8 Complaint from e-mail → Reklamácia prijatá
`CreateReceivedComplaint(ReceivedComplaint:{ Firma_ID, DatumPrijeti, Odkaz:<invoice/DL number>,
PopisReklamace:<customer text summary>, PopisReklamaceInterni:<AI notes>, Poznamka:"SMID:…",
Polozky:[{ Nazev, Mnozstvi, ObsahPolozky:{ Artikl_ID, Sklad_ID, Mnozstvi } }] }) { ID CisloDokladu }`
(items from the referenced invoice lines). Reply draft confirms receipt with the complaint number.

### 5.9 Order / shipping status
`ReceivedOrders(Filter:"Odkaz~eq~<PO>")` (`Stav`, `Vyrizeno`, items `MnozstviZbyva`) →
`IssuedDeliveryNotes(Filter:"Firma_ID~eq~<C>#DatumVystaveni~gte~<d>")` (`Stav`, `DatumSkladovehoPohybu`,
`ZpusobDopravy { Nazev }`) → carrier tracking numbers from carrier e-mails in the mailbox. Unknown date → placeholder.

### 5.9b PDFs that exist in the API (REST `…/{id}/Report/{reportId}` or `/{reportConfigId}`)
`IssuedInvoice` (faktúra vystavená, dobropis), `PrepaymentIssuedInvoice` (zálohová vystavená), `PrepaymentInvoice`
(zálohová prijatá), `ReceivedInvoice`, `PriceList` (v2), `Service` (v2). **No report** for delivery notes (issued or
received), orders, offers, complaints → Smart Mail renders only the offer and the order confirmation itself
(DOCUMENTS_SPEC §4–§5) and never re-creates invoices (DOCUMENTS_SPEC §6).

### 5.10 Codebooks in Settings
`Warehouses`, `NumericalSeries`, `AccountAssignments`, `VATClassifications`, `VatRates`, `Currencies`,
`PaymentTypes`, `TransportTypes`, `Centres`, `JobOrders`, `Operations`, `PriceLists` → real selects in Settings ›
Money S4 and Settings › Pobočky › Money (dropdowns loaded from Money, never typed codes; defaults per document type,
per branch and per supplier). Fields without a codebook query (`DruhPohybu_ID`, `DruhSkladovehoPohybu_ID`,
`RegistraceDPH_ID`, `TypCeny`, `DruhPolozky_ID`, `VazbaTypVazby`) are copied from the branch template document
(DOCUMENTS_SPEC §2.6).

---------------------------------------------------------------------------------------------------
## 6. Money Bridge — internal HTTP API (only component with Money credentials)

HMAC-signed requests from the main app; writes also need `X-Approval-Token` (JWT: suggestion_id, user_id, role,
sha256(payload), exp 5 min, single-use jti). No generic GraphQL proxy — only these endpoints:

| Method | Path | Money call |
|---|---|---|
| GET | `/healthz` | token + `Version` + REST ping |
| GET | `/sync/{companies,persons,articles,article-suppliers,price-history,codebooks}?since=` | GraphQL lists with `ChangeFrom` / REST |
| GET | `/companies/{id}` · `/companies/{id}/receivables` · `/orders` · `/deliveries` · `/activities` | 5.2, 5.3, 5.9 |
| GET | `/invoices/issued/search` · `/invoices/issued/{kind}/{id}/pdf?lang=` | 5.1 |
| GET | `/stock?article_ids=` (offers only, information) · `/prices?company_id=&warehouse_id=&article_ids=` | `WarehouseStocks`, `ProdejniCeny` |
| GET | `/suppliers/{id}/open-orders` · `/suppliers/{id}/template` | 5.5 |
| POST | `/match/items` (supplier_id, lines[]) | runs cascade 5.5.3 on cache + live checks, returns per-line candidates |
| GET | `/duplicates?kind=&supplier_id=&number=&vs=` | 5.5.2 |
| POST | `/delivery-notes/received` | `CreateReceivedDeliveryNote` (approval) |
| POST | `/offers/issued` (only when `IssuedOffer` exists) | `CreateIssuedOffer` + read-back (approval) |
| DELETE | `/documents/{kind}/{id}` | undo within 15 min (approval, accounting) |
| POST | `/orders/match` · GET `/customers/{id}/order-context` · `/orders/received/duplicates` · `/orders/received/by-smid/{smid}` | ORDERS_SPEC §15 |
| POST | `/orders/received` (create + read-back) · GET `/orders/received/{id}` · `/orders/received/{id}/deliveries` · DELETE `/orders/received/{id}` (undo) | ORDERS_SPEC §9, §12 |
| POST | `/complaints/received` · `/companies` · `/persons` · `/activities` | creates (approval) |

---------------------------------------------------------------------------------------------------
## 7. Filter builder (pseudo-code)
```python
def cond(field: str, op: Literal["eq","ne","sw","ct","ew","lt","lte","gt","gte"], value) -> str:
    v = fmt(value)                      # dates YYYY-MM-DD, bool true/false, decimals with dot, GUID as is
    if any(c in v for c in "~#|()"): raise UnsafeFilterValue(field)
    return f"{field}~{op}~{v}"
def all_(*c): return "#".join(c)        # AND
def any_(*c): return "|".join(f"({x})" for x in c)   # OR
```
Unit tests for every operator and for unsafe values.

---------------------------------------------------------------------------------------------------
## 8. Mock backend
`bridge/app/mock.py`: in-memory GraphQL-like responses for all bridge endpoints; seed 20 customers, 10 suppliers with
`ArticleSuppliers` codes (incl. one supplier with codes missing), 300 fastener articles with parameters and packaging,
stock in 2 warehouses, customer prices with discounts, 300 issued invoices (some overdue), 40 received invoices,
open purchase orders, delivery notes with remaining quantities; PDF endpoint returns a valid one-page PDF.

---------------------------------------------------------------------------------------------------
## 9. Questions for the Money implementer
1. Enable **`IssuedOffer` (Nabídka vydaná)** in GraphQL incl. `CreateIssuedOffer` — required: offers are numbered by
   Money (DECISIONS D5; Smart s.r.o. arranges it).
2. Report GUIDs for: faktúra vydaná SK/EN/DE, zálohová faktúra, dobropis, cenník.
3. Rights of API role "ai-bridge": read all lists in §3; create ReceivedDeliveryNote, ReceivedOrder, IssuedOffer,
   ReceivedComplaint, Company, Person, Activity (no ReceivedInvoice — D7); delete own documents (undo);
   write access to supplier codes of articles (`ArticleSupplier` create/edit or `SeznamDodavatelu` in `ArticleInput`).
4. ~~Mode A/B for received invoices~~ — not needed, received invoices are not handled (D7).
5. Date format in filters, escaping, page limit, API version policy (API version must match Money version).
6. Can Activities, Persons and prepayment invoices be added to GraphQL (to drop REST later)?
7. Customer orders: the 9 questions in `docs/ORDERS_SPEC.md` §20 (requested delivery date field, reservation,
   discount re-application, enum meanings, text lines, delivery-note link, `Odkaz` length, e-shop orders, order report).
8. Branches: is the branch price list (`Cenik_ID`) needed on received delivery note / invoice items, or are centre
   (`Stredisko_ID`) and warehouse (`Sklad_ID`) enough? Does each branch have its own numerical series?
   (`money_probe.py --branches` answers most of it from existing documents.)
9. Received delivery note: is "Doklad prijatý" stored in `Odkaz` (probe `template_check`)? Does
   `CreateReceivedDeliveryNote` fill the supplier address from `Firma_ID`, or must `Adresa*` be sent? Smart Mail
   sends `DatumUcetnihoPripadu` = `DatumSkladovehoPohybu` = date of the write (D13) — does Money accept it as is? (Fees
   are not written — D14.)
10. PDF reports for `IssuedDeliveryNote` (dodací list vydaný — customers ask for copies) and `ReceivedOrder`
    (order confirmation) — can REST report endpoints like `IssuedInvoice/{id}/Report/{reportId}` be enabled?
11. Together with question 1: when `IssuedOffer` is enabled, also a report endpoint for offers (then Smart Mail can
    attach the original Money PDF and stop rendering its own).
