# Money S4 probe — findings from the TEST agenda (2026-10-31, #176)

Source: `probe_output/report.md`, `orders.md`, `branches.md` (PR #175), API version 1.15.11.7730. This file turns the
raw probe output into decisions for the code and the specs. The probe exports counts only, never business values.

## 1. Transport and response shape (already fixed — #170, #171)
- Every answer (GraphQL and REST) is wrapped in `{"PageCount","RowCount","Data","Status","Message","StackTrace"}`,
  `Status` 1 = OK. `gql_client.unwrap` removes the wrapper; a different status → `MoneyError`. The message and the
  stack trace are never logged.
- REST DTOs have **PascalCase** keys although the swagger says camelCase. All REST mappers in `bridge/app/api_backend.py`
  read keys case-insensitively (`_ci`): persons, activity types. Tests with the real shape (fictional values):
  `bridge/tests/test_api_backend.py` (`…_real_api_envelope_with_pascal_case_fields`).
- No other REST mapper exists yet. Issued invoices, orders and delivery notes come from GraphQL. Proformas and
  activities have no REST mapper because they would need REST filters (see §3).

## 2. GraphQL filters — confirmed
`eq` `ct` `sw` `ew` and OR (`|`) work. Dates work as ISO `2026-10-31`, SK `31.10.2026` and ISO with time. The bridge
keeps ISO (`filters.fmt`). Escaping `~ # | ( )` inside a value was not tested, so such values stay rejected
(`UnsafeFilterValue`). No server-side ordering (`OrderProperties` gives an unclear order) → client-side sort stays.

## 3. REST — only for PDF, persons and activity types
- REST list filters (`Filters`, `PropertyName`, …) and `?text=` **do not work**: no syntax returned only the probe
  invoice. Decision: search only through GraphQL. REST stays for PDF reports, `Person/{from}/{count}` and
  `TypeOfActivity/{from}/{count}`.
- Consequences:
  - **Proformas** (`PrepaymentIssuedInvoice`) cannot be searched on the API backend. Invoice copies work for issued
    invoices. Proforma PDFs work when the ID is known.
  - **Activity history** (W9a tab Aktivity) stays `waiting_for_probe` on the API backend, because a REST list would
    have to be filtered client-side.
  - **Writing activities (3f)** stays off. The SMID duplicate check cannot use a REST filter, and the required fields of
    `ActivityInputDto` are not confirmed. Proposal for Erik: one write test on the TEST agenda (create 1 activity →
    read it back by ID → delete it), then a decision on the SMID check (client-side scan of the newest page, or
    Activities in GraphQL — MONEY_API §9 question 6).
- Without paging, REST returns 1 000 rows in about 6.7 s (server `DefaultPageLimit`). REST paging starts at the oldest
  record. The bridge always pages (≤ 500).

## 4. PDF of an issued invoice — works
`GET /v2.0/IssuedInvoice/{id}/Report/{reportId}` → 200, `application/octet-stream`, valid PDF in about 5.1 s. The bridge
timeout (read 20 s) is enough (test `test_bridge_timeout_covers_slow_pdf_report`). Report per branch: #174.

## 5. `ProdejniCeny` returns 0 rows — analysis and proposal (needed before Phase 4, `ORDER_PRICE_MODE`)
Facts:
- `ProdejniCeny(FirmaID:…, Count:5)` → 0 rows, no error, 55 ms, for the company `PROBE_COMPANY_ICO`. The company has no
  own discount (`test_company_has_discount: false`).
- Schema: `ProdejniCeny(Filter, From, Count, FirmaID: Guid!, SkladID: Guid, MenaID: Guid)`.
- 15 price lists. 12 of them are branch price lists (`10/20/30/40` × `s DPH`/`bez DPH`, plus `13 PKT`, `99`), and
  each has a default warehouse (`VychoziSklad_ID`). `A1/A2/A3`, `MPC` and the inactive one have none.
- 292 / 896 order items carry a price list.

Most likely cause: Money computes selling prices **per warehouse** (price list ↔ default warehouse). Without `SkladID`
no price list applies, so the answer is empty. Other possibilities: the probe company has no price-list assignment
(`CompanyPriceLists`), or the API role cannot read prices.

Proposal:
1. `money_probe.py` now also asks once per warehouse with `SkladID` (read-only, counts only, step
   „ProdejniCeny with SkladID“). Erik re-runs `money_probe.py` on TEST.
2. If a warehouse returns rows → the bridge always sends `SkladID` = branch warehouse (11e). ORDER_PRICE_MODE is then
   decided by `TypCeny` / `MnozstevniSleva` in those rows (`--orders` re-run).
3. If all are 0 → read `CompanyPriceLists` for the probe company and ask the Money implementer
   (MONEY_API §9 question 12). Fallback for Phase 4: price from the branch price list via `PriceListItems`
   (`Cenik_ID` = branch price list) + company discount `HodnotaSlevy`. This needs Erik's approval.

## 6. `IssuedOffer` is not in the schema
Phase 6 stays blocked (D5). Nothing is built.

## 7. Received invoices: 0/309 items linked to a source item, 305 with article
Recorded only. Received invoices are not handled at all (D7), so Mode A/B is not needed (MONEY_API §9 item 4). The
evidence agrees: in Money, invoices are not created by copying delivery note items.

## 8. Received orders (`--orders`, 200 orders / 896 items)
| Finding | Consequence |
|---|---|
| `Odkaz` filled in 1/200 (max seen 19 chars) | Smart Mail fills `Odkaz` = customer PO. The real max length is still unknown (ORDERS_SPEC §6: full number also in `Poznamka`). |
| `Odkaz~eq~` and `Poznamka~sw~SMID:` work | The duplicate checks D1–D5 and the SMID marker are possible as specified. |
| `Stav` and `Vyrizeno` 0 everywhere, `PriznakVyrizeno` 77/200, `Faze` 1, `Storno` 0 | Status sync (ORDERS_SPEC §12) must use `PriznakVyrizeno` (+ `DatumVyrizeni`, 199/200), not `Stav`/`Vyrizeno`. |
| 133 items without article | Text lines exist in real orders. The confirmation and the review screen must show them (ORDERS_SPEC §20 question on text lines). |
| `TypCeny` 0 (861) / 1 (35) | Meaning of 0/1 is not documented → copy from template documents, never guess. |
| Units: `ks`/`bal` 0 decimals, `kg` 3 decimals; 34 units with `NedelitelneMnozstvi` | Quantity validation uses `DesetinnaMista`. **No rounding to packaging** (D6/D17) — an indivisible quantity is only a warning, never a change. |
| `Rezervovano` 0, partially fulfilled 0 | Agrees with D6 (no stock handling). |
| 11 items of 100 delivery notes have a source item, 0 point to order items | „Tovar odoslaný“ (ORDERS_SPEC §12) cannot rely on `ZdrojovaPolozkaKopirovani_ID` → match by `Odkaz`/company/date. |
| Obchodník / Osoba never filled | Not written by Smart Mail either. |

## 9. Branches and received delivery notes (`--branches`, 300 notes / 3 206 items)
| Finding | Consequence |
|---|---|
| Centres **10 Trnava, 20 Senica, 30 Nitra, 40 Trenčín** | 11e: centre per branch. |
| Warehouses = same codes + **99 Externý sklad** | Centre code = warehouse code (Senica had 1 item in Trnava). Warehouse 99 is never a branch default. |
| Series per centre: `DLP TT/SE/NR/TN` (1 Senica note in `DLP TN`) | 11e `series_overrides` per branch is required. |
| `Predkontace` FP010 in 300/300 | Copied from the branch template document (DOCUMENTS_SPEC §2.6), never hard-coded. |
| Items with `Cenik_ID`: 0 / 3 206 | **Contradicts MONEY_API §5.5.9** (items get the branch price list) → question below. |
| Item `Stredisko` = header in 0 / 3 206 | Counts only; most likely `null` on items. **Contradicts §5.5.9** (items get the branch centre) → question below. |
| `PartnerskyKod` in 616 / 3 206 | Supplier code is used, as in DOCUMENTS_SPEC §2.5. |
| `Odkaz` in 233/300, max 18 chars | „Doklad prijatý“ = `Odkaz`, as specified. `template_check` was not run (`PROBE_DL_NUMBER` missing). |
| `TypCeny` 0/2 (1 → 2 items), `VazbaTypVazby` 1, one `DruhPohybu_ID`, two `DruhSkladovehoPohybu_ID` | Copied from the template document. |
| Stock movement on the issue day in 289/300 | Agrees with D13. |
| Side costs on 29 notes / 133 items, document discount on 7 | Information only (D14). |

## Otázka pre Erika
1. **Položky dodacieho listu prijatého – `Stredisko_ID` a `Cenik_ID`.** V Money nemá stredisko ani cenník žiadna z 3 206
   položiek (stredisko je len v hlavičke). MONEY_API §5.5.9 a CLAUDE.md §7 však hovoria, že stredisko pobočky sa zapisuje
   do hlavičky aj do položiek a cenník pobočky do položiek. Navrhujem robiť to ako Money: stredisko len v hlavičke a
   položky bez `Cenik_ID`. Súhlasíš? (Inak by doklady zo Smart Mail vyzerali inak ako tie, ktoré robia ľudia ručne.)
2. **Cenník pobočky (11e):** každá pobočka má dva cenníky („s DPH“ a „bez DPH“). Ktorý je cenník pobočky pre objednávky
   (fáza 4)? Navrhujem „bez DPH“, lebo objednávky a ponuky sú v cenách bez DPH.
3. **`ProdejniCeny`:** prosím spusti `money_probe.py` (a `--orders`) znova na TEST. Nový krok skúša ceny po skladoch (§5).
