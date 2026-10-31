# DOCUMENTS_SPEC.md — documents that look like Money S4 (v2.8)

Binding for: received delivery note card (W6h), print documents rendered by Smart Mail (offer, order confirmation),
invoice PDFs from Money, branch values on documents, document numbering. Read together with MONEY_API.md §5.5,
ORDERS_SPEC.md, SCREENS_SPEC.md (W6e/W6h, W7/W7a/W7b, W6g), SETTINGS_SPEC.md (11e, 13, 15).

Source material supplied by Smart s.r.o. (analysed for v2.5; every customer/supplier value in this package is
FICTIONAL — never copy real values from the originals into fixtures, Figma or tests):
- screenshot of the Money card "Dodací list prijatý … – Karta" (tab Všeobecné with 30+ items),
- print report "Dodací list prijatý" (PDF + PRNX),
- print report "Ponuka vystavená" (PDF + PRNX = gzip DevExpress XtraReports 24.1.5 `PreviewSerializer` XML).

---------------------------------------------------------------------------------------------------
## 0. Principle

Staff work in Money every day. Whatever Smart Mail shows or prints for a Money document must use **the same labels,
the same field order, the same column order, the same number formats and the same print layout** as Money, so nobody
has to learn a second form. Three cases:

| Case | Documents | What Smart Mail does |
|---|---|---|
| A. Smart Mail prepares a Money document | Dodací list prijatý, Objednávka prijatá, Ponuka vystavená (after `IssuedOffer`, D5), Reklamácia prijatá | Review card that mirrors the Money card (§2). After approval → GraphQL `Create…` → read-back → the card shows the Money number. Printing stays in Money. |
| B. Smart Mail renders a print document itself | Potvrdenie objednávky; Ponuka vystavená (Money number) as long as the API has no offer report | PDF from `templates/print/document.html.j2` + `money_print.css`, a 1:1 copy of the Money report layout (§4, §5). |
| C. Money is the only source | Faktúra vystavená, dobropis, zálohová faktúra vystavená, (dodací list vydaný) | Smart Mail **never renders, edits or re-creates** them. It downloads the original PDF from Money (REST report) and attaches it to the e-mail unchanged (§6). |

Not a goal: re-implementing Money editing tools. Money toolbar actions that Smart Mail does not support (Cudzie meny,
Korekcia, Zrušiť zľavu, Výpočet ceny, Pridať dokladom, Kopírovať, Čiarové kódy, Výkazy, DPH tab) are **not shown**
(no disabled ghosts). After creation the card shows "Ďalšie úpravy urobte v Money – doklad {číslo}".

---------------------------------------------------------------------------------------------------
## 1. Document matrix

| Document (Money name) | Created by | Smart Mail screen | PDF | API |
|---|---|---|---|---|
| Dodací list prijatý | Smart Mail draft → user approves | W6h card (§2) | Money prints it; Smart Mail keeps the supplier original | GraphQL `CreateReceivedDeliveryNote`, read `ReceivedDeliveryNote(ID)` |
| Faktúra prijatá | **not handled by Smart Mail** (DECISIONS D7) — people enter it in Money | — (the supplier invoice is only the source of the delivery-note lines) | — | — |
| Objednávka prijatá | Smart Mail draft → approval | W6f/W6g (ORDERS_SPEC) | Potvrdenie objednávky rendered by Smart Mail (§5) | GraphQL `CreateReceivedOrder` (no REST report exists) |
| Ponuka vystavená | Smart Mail draft → approval → **created in Money, Money number** (D5) | W7a editor, W7b PDF | Money report if the API gets one, else rendered by Smart Mail (§4) with the Money number | GraphQL `CreateIssuedOffer` (Smart s.r.o. arranges `IssuedOffer`) |
| Faktúra vystavená, dobropis | Money only | link + attach (W4, W3b) | **original Money PDF** REST `/v2.0/IssuedInvoice/{id}/Report/{reportId}` | REST |
| Zálohová faktúra vystavená | Money only | link + attach | REST `/v2.0/PrepaymentIssuedInvoice/{id}/Report/{reportId}` | REST |
| Cenník | Money only | attach on request | REST `/v2.0/PriceList/{id}/Report/{reportId}` | REST |
| Dodací list vydaný | Money only | status only (ORDERS_SPEC §12) | **no report endpoint in the API** → cannot be attached automatically (MONEY_API §9 question 10) | GraphQL read only |
| Reklamácia prijatá | Smart Mail draft → approval | W8c | none | GraphQL `CreateReceivedComplaint` |

---------------------------------------------------------------------------------------------------
## 2. Dodací list prijatý — card W6h (mirror of "Dodací list prijatý – Karta")

Route `/docs/delivery-notes/:id` (list W6e stays at `/docs/delivery-notes`). Roles: warehouse, accounting, admin.
Desktop ≥ 1280 px uses the Money layout below. Below 1280 px and on mobile (M13b) the same groups are stacked in the
same order (Hlavička → Dodávateľ → Dátum → Podrobnosti → DPH → Položky).

### 2.1 Frame (top → bottom)
1. **Page header**: "Dodací list prijatý" + number (before create: "nový – návrh") + status chip
   (Návrh / Chýbajú údaje / Pripravený / Zapisuje sa… / V Money / Chyba / Neistý stav / Vrátený) + branch chip
   (short BranchChip "Pobočka Senica · stredisko 20 · sklad 20"; the page header uses the full text, UX_SPEC, D23).
2. **Action bar** (Money toolbar order, only supported actions):
   `Vytvoriť v Money` (primary; = Money "OK") · `Späť` (= close without saving changes) · `Pridať do adresára`
   (only when the supplier is not in Money → company_create suggestion). No `Náklady` button — fees are not handled
   (DECISIONS D14). Right side: `Originál dokladu` (toggles the PDF panel) · `Kontrola (n)`.
3. **Tabs** (Money names, Money order, only those Smart Mail fills): `Všeobecné` · `Pripojené dokumenty` · `Texty` ·
   `Poznámka`. (Výkazy and DPH are Money-only.)
4. **Right panel 420 px** (Smart Mail addition, collapsible): `Originál` (supplier PDF/XML with highlighted values,
   click on a field → highlights its bbox) and `Kontrola` (rules §2.7 with links to the field/line).

### 2.2 Tab Všeobecné — header, left part (exact Money layout: 2 columns of label/field pairs)

Column 1 (labels right-aligned, fields 150 px) and column 2 (labels right-aligned, fields 150 px), then two groups
"Dátum" (column 1) and "Podrobnosti" (column 2) with blue group titles — same as Money.

| Money label | Pos. | GraphQL field (ReceivedDeliveryNoteInput) | Value in Smart Mail | Edit | Rule |
|---|---|---|---|---|---|
| Číslo dokladu | c1 r1 | `CisloDokladu` (assigned by Money) | "bude pridelené" → read-back number | no | — |
| (series box next to number, e.g. "DLP SE") | c1 r1 | `CiselnaRada_ID` | branch series (SETTINGS 11e) → company default (13c) | select (admin) | DL-B1 |
| Popis | c1 r2 (wide) | `Nazev` | Money default = name of item 1; Smart Mail fills the same, editable (max 100) | yes | — |
| Doklad prijatý | c1 r3 | `Odkaz` **[PROBE --branches template_check]** | supplier delivery-note number; if the supplier sent only an invoice → invoice number | yes | DL-B3 duplicates |
| Párovací symbol | c2 r3 | `ParovaciSymbol` | supplier invoice number / VS when the DL refers to an invoice, else empty | yes | — |
| Vratka | c1 r4 (checkbox) | header `ZapornyPohyb` | always unchecked, read-only — returns only in Money (D15) | no | DL-B8 |
| Vybavené | c1 r5 (checkbox) | `PriznakVyrizeno` | read-only, from read-back | no | — |
| Spôsob platby | c2 r5 | `ZpusobPlatby_ID` | empty (as in Money) or supplier default | select `PaymentTypes` | — |
| Registrácia k DPH | c1 r6 | `RegistraceDPH_ID` | copied from the template document (own VAT registration) | no | never guessed |
| Doprava | c2 r6 | `ZpusobDopravy_ID` | empty or supplier default | select `TransportTypes` | — |
| **Predkontácia** (bold = required) | c1 r7 | `Predkontace_ID` | supplier default (SETTINGS 13) → template (e.g. FP010) | select `AccountAssignments` | DL-B6 |
| Druh pohybu | c2 r7 | `DruhPohybu_ID` | copied from the template ("obstaranie") | no (shows template label) | DL-B6 |
| Druh skl. pohybu | c2 r8 | `DruhSkladovehoPohybu_ID` | copied from the template ("príjem") | no | DL-B6 |
| **Dátum** › Vystavenie | c1 g1 | `DatumVystaveni` | date of the supplier document (extraction) | date | DL-W4 |
| Dátum › Účt. prípadu | c1 g2 (grey) | `DatumUcetnihoPripadu` | = date of stock movement (D13); before create "pri zápise" | no | — |
| Dátum › Sklad. pohybu | c1 g3 (date + time) | `DatumSkladovehoPohybu` + `CasSkladovehoPohybu` | **moment of the write to Money** = approval time, Europe/Bratislava (DECISIONS D13); before create the grey field shows "pri zápise do Money", after read-back the real value | no | — |
| **Podrobnosti** › Stredisko | c2 g1 | header `Stredisko_ID` + every item `Stredisko_ID` | branch centre (SETTINGS 11e) | read-only chip; admin "Zmeniť" | DL-B1, DL-B9 |
| Podrobnosti › Zákazka | c2 g2 | `Zakazka_ID` | empty / supplier default | select `JobOrders` | — |
| Podrobnosti › Činnosť | c2 g3 | `Cinnost_ID` | empty / supplier default | select `Operations` | — |
| Zľava [%] | c2 g4 | `Sleva` | 0,00 — supplier discounts are already in the net line prices; never a header discount | no | — |
| Celk. obstar. c… | c2 g5 (grey) | computed (`CelkovaPorizovaciCena` after read-back) | Σ line totals | no | — |

### 2.3 Tab Všeobecné — header, right part

Sub-tabs (Money): `Dodávateľ` · `Kon. príjemca` · `Fakt. adresa`. Fields of Dodávateľ in Money order: IČO, DIČ,
"DPH" badge (VAT payer), IČ DPH, Názov firmy, Osoba, Ulica, PSČ, Mesto, Štát. All read-only from the Money company
(`Firma_ID`); the extracted values are shown as small grey hints only when they differ (then DL-B2).
**[PROBE on TEST]** whether `CreateReceivedDeliveryNote` with only `Firma_ID` fills `AdresaNazev/AdresaUlice/…`;
if not, the bridge sends `AdresaNazev, AdresaUlice, AdresaMisto, AdresaPSC, AdresaStat_ID, IC, DIC, ICDPH` from the
company card (never from the PDF).

**VAT recap** under the address block (Money layout): rows `Nulová 0 %`, `Znížená 5 %`, `Znížená 19 %`,
`Základná 23 %` (rates and labels from `VatRates`; rows with no amount stay visible with 0,00 as in Money) × columns
`Základ`, `DPH`, `Vrátane DPH`; row with currency select (`Mena_ID`, EUR) and totals; row `V domácej mene`.
Reverse charge (supplier from another EU country): the rate stays 23 % and DPH = 0,00 (exactly as Money shows it),
chip "Prenesenie daňovej povinnosti"; DL-W3 compares this with the supplier document.

### 2.4 Items — tabs `Položky` · `Poplatky`

**Item toolbar** (Money order, supported only): `Opraviť` (opens the line drawer) · `Opraviť hromadne` (set warehouse /
VAT rate / Typ ceny for selected lines) · `Pridať výberom` (catalog search, adds a stock line) · `Zmazať` ·
`Excel` (export XLSX of the grid) · `Σ` (sum row on/off) · `Legenda` (status colours) · `Nahor` · `Dolu`.

**Grid columns** — Money order. Smart Mail adds a status column at the start and two code columns after Názov
(they are the heart of the matching, so they are visible by default). "Stĺpce" menu: preset `Ako v Money` (all Money
columns in Money order) and `Kontrola príjmu` (default below). Column widths and order are saved per person.

| # | Column (SK) | Source | Before create | After read-back | Default |
|---|---|---|---|---|---|
| – | (stav) | matching status icon | ✓ green / ! amber / ✕ red / T text line | ✓ | on |
| 1 | Poradie | `Poradi` | 1…n (Nahor/Dolu) | same | on |
| 2 | Názov | `Nazev` | **Money article name** (`Article.Nazev`), not the supplier text | same | on |
| 3 | Katalóg | `Katalog` | our internal catalog number (`Article.Katalog`) | same | on |
| 4 | Kód dodávateľa | `ObsahPolozky.PartnerskyKod` | supplier code from the document | same | on |
| 5 | Kód skladu | `ObsahPolozky.Sklad_ID` → `Warehouse.Kod` | branch warehouse (SETTINGS 11e); select with all Money warehouses (D18) | same | on |
| 6 | Počet MJ | `Mnozstvi` (+ `ObsahPolozky.Mnozstvi`) | converted to our unit, 4 dp | same | on |
| 7 | MJ | `Jednotka` | article main unit (ks, kg, m, bal) | same | on |
| 8 | Sadzba DPH | `SazbaDPH_ID` → % | from the document line | same | on |
| 9 | Typ ceny | `TypCeny` | copied from the template ("Iba základ") — never guessed | same | on |
| 10 | Jedn. cena | `JednCena` | net unit price in our unit, 4 dp | same | on |
| 11 | Celková cena | computed | round(qty × price, 2) | `CelkovaCena` | on |
| 12 | Vratka | `Vratka` | false | same | Money preset |
| 13 | Číslo položky | `CisloPolozky` | — | from Money | Money preset |
| 14 | Typ väzby | `ObsahPolozky.VazbaTypVazby` | copied from template | from Money | Money preset |
| 15 | Celková obstarávacia | `CelkovaPorizovaciCena` | — | from Money | Money preset |
| 16 | Celkové dodatočné náklady | `CelkoveVedlejsiNaklady` | 0 | from Money | Money preset |
| 17 | Čiarový kód | `Article.CarovyKod` | from catalog (read-only) | same | on |
| 18 | Prevzatý typ | — | — | from Money | Money preset |
| 19 | Jednotková obstarávacia | `JednotkovaPorizovaciCena` | — | from Money | Money preset |
| 20 | Jedn. dod. náklady | `JednotkoveVedlejsiNaklady` | 0 | from Money | Money preset |
| 21 | Vybavené | `PriznakVyrizeno` | — | from Money | Money preset |
| 22 | Druh položky | `DruhPolozky_ID` → label ("tovar") | copied from template | same | on |
| 23 | Zostáva | `Zbyva` | — | from Money (waiting for invoice) | Money preset |

Hidden-but-sent per item: `Stredisko_ID` (= header), `ObsahPolozky { Artikl_ID, Sklad_ID, Mnozstvi, Jednotka_ID,
Cenik_ID (branch price list if MONEY_API §9 question 8 says so), PartnerskyKod, PartnerskyNazev }`.
Number formats exactly as Money: quantity `50,0000`, unit price `1,2215`, totals `61,08`, thousands with a space.
Text lines (no article, e.g. "Doprava") → see `Poplatky`.

**Poplatky** tab: read-only list of non-goods lines found on the supplier document (doprava, balné, palety, poistenie,
manipulačný poplatok) with amounts and the info "Poplatky sa nezapisujú – ak treba, doplňte ich v Money" (DECISIONS
D14 — fees are not handled for now; nothing in the payload, `CelkoveVedlejsiNaklady` stays 0). The totals check DL-B7
counts goods lines + listed fees against the supplier total (it verifies the extraction, not the write).

### 2.5 Matching our catalog number ↔ supplier code (MONEY_API §5.5.3)
`Katalóg` is our internal number; each article card in Money has the supplier's codes (`ArticleSuppliers`:
`Parent_ID` = article, `Firma_ID` = supplier, `DodavatelskyKod`, `DodavatelskyNazev`, `Jednotka`, `PosledniCena`).
For every supplier line: normalized supplier code + supplier `Firma_ID` → `ArticleSuppliers` → article →
`Katalog`, `Nazev`, main unit, barcode. Example (fictional): Fixtech CZ line "FX-933-1030-A2 Šroub ISO 4017 M10x30 A2,
25 bal à 200" → Katalóg `309903010030` "skr. M10 x30 A2 DIN 933", 5 000,0000 ks, price per ks = price per bal / 200.
Fallbacks in order: learned mapping (confirmed in Smart Mail) → EAN → our code/catalog written on the document →
open purchase order → fastener attributes (AI, must be confirmed) → manual pick. A confirmation never writes to the
Money catalog (API has no write for supplier codes); Settings › Money S4 › Kódy dodávateľov exports the learned pairs
(CSV) so the purchasing clerk can add them to the article cards — after the next cache sync they come back as rule 1.

### 2.6 Template document ("vzor")
Values that the API has no codebook for (`DruhPohybu_ID`, `DruhSkladovehoPohybu_ID`, `RegistraceDPH_ID`, item
`TypCeny`, `DruhPolozky_ID`, `VazbaTypVazby`) are **copied from the last received delivery note of the same branch
(same `Stredisko_ID`)** that was created in Money by a person (not by Smart Mail), cached per branch with its date.
Admin can pin a specific document as the template in SETTINGS 11e ("Vzorový dodací list pobočky"). No template →
DL-B6 blocks with "Pobočka nemá vzorový dodací list – vytvorte jeden v Money alebo vyberte vzor v Nastaveniach".

### 2.7 Validation (blocking DL-B, warnings DL-W) — every rule has a test named after its id
| Id | Rule | Message (SK) |
|---|---|---|
| DL-B1 | Branch has centre, warehouse and series (SETTINGS 11e) | "Pobočka nemá v Nastaveniach priradené stredisko/sklad/číselný rad z Money." |
| DL-B2 | Supplier exists in Money (`Firma_ID`) and IČO equals the document | "Dodávateľ nie je v adresári Money / IČO nesedí." |
| DL-B3 | No received DL with the same supplier + `Odkaz`, no document with the same SMID | "Tento dodací list už v Money je: {číslo}." |
| DL-B4 | Every goods line has an article or is explicitly marked "neskladová položka" | "{n} riadkov nie je spárovaných." |
| DL-B5 | Every stock line has a `Sklad_ID` (any warehouse from the Money list, D18) | "Riadok {n} nemá sklad." |
| DL-B6 | Predkontácia, Druh pohybu, Druh skl. pohybu, Typ ceny present (template) | "Chýba vzorový dodací list pobočky." |
| DL-B7 | Σ goods lines (+ listed fees) = supplier document total per VAT rate (± 0,01) | "Súčet riadkov {x} ≠ doklad {y}." |
| DL-B8 | All quantities > 0 (returns only in Money, D15) | "Záporné množstvo – vratku urobte v Money." |
| DL-B9 | Item `Stredisko_ID` = header `Stredisko_ID` | (internal, should never fire) |
| DL-B10 | Approval token valid, person has role warehouse/accounting, payload hash unchanged | "Návrh sa medzičasom zmenil – skontrolujte ho znova." |
| DL-W1 | Unit price differs from `ArticleSupplier.PosledniCena` by more than the SETTINGS 14 threshold (10 %) | "Cena o {x} % vyššia ako minule." |
| DL-W2 | Quantity differs from the open purchase order | "Objednané {a}, dodané {b}." |
| DL-W3 | VAT mode differs from the document (reverse charge vs. domestic) | "Doklad je s prenesením DP, návrh nie." |
| DL-W4 | Vystavenie (date of the supplier document) is in the future or older than 30 days | "Skontrolujte dátum vystavenia." |
| DL-W5 | Fees on the supplier document are not written (Poplatky, D14) | "Poplatky {suma} sa nezapisujú – doplňte ich v Money, ak treba." |
| DL-W6 | Line matched by a learned mapping that is not yet in the Money catalog | "Kód dodávateľa nie je v karte artikla – exportovať." |
| DL-W7 | Article is inactive / blocked for purchase in Money | "Artikel je neaktívny." |
| DL-W8 | Line warehouse is not the branch warehouse (allowed, D18) | "Riadok {n} ide na sklad {kód} – nie je to sklad pobočky." |

### 2.8 Create call (bridge `POST /delivery-notes/received`, approval JWT, SMID in Poznamka)
```graphql
mutation CreateDL($dl: ReceivedDeliveryNoteInput!) {
  CreateReceivedDeliveryNote(ReceivedDeliveryNote: $dl) {
    ID
    CisloDokladu
    Polozky { ID CisloPolozky Zbyva CelkovaPorizovaciCena }
  }
}
```
Variables (fictional): `{ "dl": { "Firma_ID": "<supplier>", "CiselnaRada_ID": "<branch series>",
"Stredisko_ID": "<branch centre>", "Odkaz": "DL-2026-04417", "ParovaciSymbol": "2611452", "Nazev": "skr. M10 x30 A2 DIN 933",
"DatumVystaveni": "2026-10-20", "DatumUcetnihoPripadu": "2026-10-21", "DatumSkladovehoPohybu": "2026-10-21",
"CasSkladovehoPohybu": "2026-10-21T09:14:00" (= approval time, D13), "Predkontace_ID": "<template>", "DruhPohybu_ID": "<template>",
"DruhSkladovehoPohybu_ID": "<template>", "RegistraceDPH_ID": "<template>", "Mena_ID": "<EUR>", "Sleva": 0,
"Poznamka": "SMID:dl_7f3a… · zdroj: e-mail 2026-10-21", "Polozky": [ { "Poradi": 1, "Nazev": "skr. M10 x30 A2 DIN 933",
"Katalog": "309903010030", "Mnozstvi": "5000", "Jednotka": "ks", "JednCena": "0.0612", "TypCeny": <template>,
"SazbaDPH_ID": "<23 %>", "Stredisko_ID": "<branch centre>", "DruhPolozky_ID": "<template>", "ObsahPolozky": {
"Artikl_ID": "<article>", "Sklad_ID": "<branch warehouse>", "Mnozstvi": "5000", "PartnerskyKod": "FX-933-1030-A2",
"PartnerskyNazev": "Šroub ISO 4017 M10x30 A2" } } ] } }`. Decimals travel as strings and are parsed with Decimal.
After create: read-back `ReceivedDeliveryNote(ID)` → compare item count, quantities, prices, totals and warehouse per
line; any difference → red banner + "Vrátiť" (`DeleteReceivedDeliveryNote`, 15 min, accounting, only if not invoiced).

### 2.9 States
`draft → needs_input → ready → creating → created` (+ `failed`, `unknown` = timeout after the mutation → reconcile by
SMID before anything else, `undone`, `rejected`). Same state machine and idempotency as ORDERS_SPEC §9.

---------------------------------------------------------------------------------------------------
## 3. Faktúra prijatá — not handled (DECISIONS D7)
Smart Mail does not create received invoices. A supplier invoice that comes with the goods is read only to build the
received delivery note (§2): its number goes to `ParovaciSymbol` (and to `Odkaz` when the supplier sent no delivery
note). The accountant enters the invoice in Money as today and pairs it with the delivery note there.

---------------------------------------------------------------------------------------------------
## 4. Ponuka vystavená — PDF identical to the Money report

### 4.1 When Smart Mail renders it
Offers are created in Money with `CreateIssuedOffer` and numbered by Money (DECISIONS D5 — Smart s.r.o. arranges
`IssuedOffer` in the API). The REST API has no report endpoint for offers today, so the PDF is rendered by this
template with the Money number. If the implementer adds an offer report (MONEY_API §9 question 11), Smart Mail attaches
the original Money PDF instead and this template is used only for the order confirmation.

### 4.2 Page and fonts (measured from the PRNX)
A4 portrait; content box 184,2 mm wide, left/top margin 12,7 mm; footer area 25 mm. Font **Arial Narrow** (Money) →
fallback **Liberation Sans Narrow** (metric-compatible, free; the Docker image installs it; render test fails if
neither is present). Sizes: body 8,25 pt; table header and VAT header 9 pt bold; customer address 9,75 pt; customer
name 10 pt bold; title and number 14,25 pt bold; "Celková čiastka" and amount 15 pt bold; footer system line 6,75 pt.
Colours: band and table header `#D6E3F2` (Money 214,227,242); rounded boxes border `#CECECE`; footer link MediumBlue
`#0000CD` bold underlined; logo navy `#2F2482` (own logo file).

### 4.3 Layout (top → bottom, positions in `money_print.css`)
1. **Company block** (Settings 11 company profile): name (bold), street, PSČ + city; middle column IČO, DIČ, IČ DPH and
   the commercial-register sentence; third column Tel., Fax; top right **Code128 barcode of the document number**.
2. **Blue band** 16,7 mm high: rounded left piece, white logo field with the company logo, blue field with
   "Ponuka vystavená č." right-aligned and a white rounded box with the number.
3. **Partner** (right, from Money company): name bold, street, PSČ + city, country, IČO + DIČ, IČ DPH.
   **Dates** (left, bold labels): Dátum vystavenia, Dátum platnosti od, Dátum platnosti do, Dátum vybavenia.
4. Optional intro text (offer text "pred cenami").
5. **Item table**: header band `Označenie dodávky | Katalóg | Počet MJ | Cena za MJ | Sadzba | Základ | Celkom s DPH`;
   rows 4,2 mm; quantity and unit price 4 dp, Základ 2 dp, Celkom s DPH 2 dp + " €"; header repeats on every page;
   a row never breaks across pages.
6. **Totals**: left rounded box "Sadzba DPH | Základ | Výška DPH | Celkom" with one row per rate (`základná 23%` …) and
   `CELKOM`; note "Rozpis DPH uvedený v mene €"; right "Celková čiastka" + rounded box with the total.
7. Optional closing text (terms, delivery time, validity) — SETTINGS 15 default text per language.
8. **Footer on every page**: light-blue bracket line with `Vystavil: {autor}` · `smartsro.sk` (link) ·
   `Vytlačil(a): {aktívna osoba}`; below the system line and `strana/počet`.
   System line text: **"Spracované systémom Smart Mail · ceny a zásoby z Money S4"** (honest — the document was not
   produced by Money; editable in SETTINGS 15).

### 4.4 Data mapping
| PDF element | Source |
|---|---|
| Company block, logo, web | SETTINGS 11 (company profile; IČO/DIČ/IČ DPH/register text default from Money `MojeFirma*` fields of the template document) |
| Number | Money `CisloDokladu` of the created offer (D5) |
| Dátum vystavenia / platnosti od / do | offer editor (od = vystavenie; do = od + SETTINGS 15 "Platnosť ponuky" days, default 14) |
| Dátum vybavenia | empty until the offer is accepted (then acceptance date) |
| Partner | Money company of the customer (`Company`: Nazev, adresa, ICO, DIC, ICDPH) |
| Označenie dodávky / Katalóg / MJ | Money article `Nazev`, `Katalog`, main unit (never the customer's wording; the customer's code can be shown as a second line "Váš kód: …" if SETTINGS 15 "Zobraziť kód zákazníka" is on) |
| Počet MJ | offer line quantity exactly as entered — never rounded to packaging (DECISIONS D17) |
| Cena za MJ | net unit price (customer price from `ProdejniCeny.CenaBezDanePoSleve` or manual), 4 dp |
| Sadzba | article VAT rate |
| Vystavil | person who created the offer; Vytlačil(a) = active person at render time |

### 4.5 Calculation and rounding (as Money; Decimal only — reference `tools/render_print.py`)
line Základ = round(qty × unit price, 2); line Celkom s DPH = round(Základ × (1 + sadzba), 2) (informative);
VAT recap per rate: Základ = Σ line bases, DPH = round(Základ × sadzba, 2), Celkom = Základ + DPH;
Celková čiastka = Σ recap Celkom. ROUND_HALF_UP. If the Money agenda uses a different rounding of the total
(`ZaokrouhleniCelkovaCastka_ID` on the template document), the same rounding is applied and shown as an extra recap
row "Zaokrúhlenie" — covered by a fixture.

### 4.6 Files in this package
- `templates/print/document.html.j2` — one Jinja2 template for the offer and the order confirmation.
- `templates/print/money_print.css` — Money geometry and styles (mm).
- `templates/print/assets/logo.png` — company logo taken from the Money report (replace via SETTINGS 11).
- `tools/render_print.py` — reference renderer (formatting, totals, Code128, WeasyPrint).
- `fixtures/documents/offer_sample.json` + `.pdf` + `.png` — fictional offer (golden file).
- `fixtures/documents/order_confirmation_sample.json` + `.pdf` + `.png` — fictional order confirmation (golden file).
- `fixtures/documents/received_delivery_note_sample.json` — fictional W6h draft (branch values, template values,
  3 lines with supplier codes, a fee, supplier totals) for UI tests, Figma content and rule tests DL-B7/DL-W5.

### 4.7 Tests
Golden render test per fixture (rasterise 150 dpi, pixel diff < 0,5 %); font presence test; number-format property
tests (`hypothesis`: thousands, negatives, 4 dp); totals tests incl. two VAT rates and a text line; long names
(cut at the cell edge like Money — no wrapping); 60-line offer → 3 pages, header repeated, footer with 1/3 2/3 3/3;
customer without IČ DPH (row hidden). Labels are Slovak in the template; EN/DE variants are added only after
Smart s.r.o. sends the Money report in that language (Q-D6).

---------------------------------------------------------------------------------------------------

## 5. Prehlásenie o zhode (atest 2.1) — issued by Smart Mail (#139, ADR-015)

- **Look**: Erik's approved template (`design/reference/prehlasenie_o_zhode/`), ported to
  `templates/print/conformity.html.j2` + `conformity.css`, rendered with WeasyPrint. A4, top band, logo, header from the
  branch (name, address, phone), footer = company seat + IČ DPH (+ IČO from `org_settings` › `company` when set) +
  „Strana X / Y“. Font Liberation Sans 2.1.5 (bundled in `templates/print/fonts/`).
- **Content**: number `PZ-RRRR-NNNN` (one company series, restarts each year, no gaps — a counter row in `org_settings`
  locked FOR UPDATE), date, Odberateľ, Doklad / zákazka, the fixed legal texts, the products table (Názov always; Kód /
  Norma / Poznámka only when some row has them; header repeated on every page; no row limit), Miesto a dátum, Vystavil
  (the branch manager's name and function), the stamp box (branch stamp + manager signature, never split).
- **Rules**: blocked without a branch stamp (`no_branch_stamp`) or a manager with a signature (`no_manager_signature`);
  sales/admin of the branch or covering it; never edited after issue (a correction is a new number); the PDF and its
  sha256 are stored (`conformity_declarations`); audit `document.conformity_issued` without customer content.
- **Files**: `fixtures/documents/conformity_sample.{json,pdf,png}` + fictional `conformity_stamp.png` /
  `conformity_signature.png` (golden test, pixel diff < 0,5 %); regenerate with `tools/make_conformity_fixture.py`.

## 5. Potvrdenie objednávky — same template, kind `order_confirmation`
Rendered after a successful `CreateReceivedOrder` + read-back (ORDERS_SPEC §10) and attached to the confirmation
e-mail. Differences to §4: title "Potvrdenie objednávky č." + Money order number (`CisloDokladu` from read-back);
dates `Dátum vystavenia`, `Vaša objednávka` (= `Odkaz`), `Požadovaný termín`, `Dodanie`; intro text "Ďakujeme za Vašu
objednávku {Odkaz}…"; text lines of the order are printed as full-width rows; no availability or delivery promises
(DECISIONS D6). If Smart s.r.o. uses a Money print report for orders (e.g. "Objednávka prijatá" / "Potvrdenie
objednávky"), they send it and the template is aligned to it like §4 (Q-D6).

---------------------------------------------------------------------------------------------------
## 6. Faktúra vystavená — only the original PDF from Money
Smart Mail never creates, renders or changes issued invoices. Flow `invoice_attach` (MONEY_API §5.1):
find the invoice → recipient/owner check → REST `GET /v2.0/IssuedInvoice/{ID}/Report/{reportId}` with the report id
of the customer's language (SETTINGS 13b "Tlačové zostavy": Faktúra SK / EN / DE, Zálohová faktúra, Dobropis) →
attach the bytes unchanged as `Faktura_{CisloDokladu}.pdf`; store sha256 in the audit log. Dobropis = issued invoice
of the credit-note type (same endpoint). Without a configured report id the invoice actions show "Nastavte tlačovú
zostavu faktúry (Nastavenia › Money S4 › Tlačové zostavy)". The report id is the GUID of the print report in Money
(the implementer provides it — MONEY_API §9 question 2; Q-D7).

---------------------------------------------------------------------------------------------------
## 7. Document numbering
| Document | Number | Rule |
|---|---|---|
| Dodací list prijatý, Objednávka prijatá, Ponuka vystavená, Reklamácia | Money (`CisloDokladu`) | Smart Mail never invents a Money number; series = branch override (11e) or company default (13c). |
| Ponuka | Money PV series (D5) | Smart Mail has no own offer series; a draft shows "návrh" until Money assigns the number. |
| Potvrdenie objednávky | = Money order number | no own series. |

---------------------------------------------------------------------------------------------------
## 8. Probe `money_probe.py --branches` (read-only) — answers before Phase 4
Lists the codebooks for SETTINGS 11e (Centres, Warehouses, PriceLists with default warehouse, NumericalSeries,
AccountAssignments) and analyses up to 300 existing received delivery notes without exporting business values:
series per centre (own series per branch?), warehouse per centre (stredisko code = warehouse code?), items with
`Cenik_ID` (needed?), `TypCeny` / `VazbaTypVazby` values, stock-movement times, vratky and side costs (information
only — D13–D15 are decided), document discounts, `Nazev` = first item, `Odkaz` usage; with `PROBE_DL_NUMBER` +
`PROBE_DL_DOKLAD_PRIJATY` it confirms that "Doklad prijatý" is stored in `Odkaz`. Output `probe_output/branches.md`.

Results on TEST (2026-10-31): `docs/probe-findings-2026-10-31.md` §9 — centres 10/20/30/40 = warehouse codes (+ 99
Externý sklad), series `DLP TT/SE/NR/TN` per centre, `Predkontace` FP010 everywhere, items without `Cenik_ID` and
without the header centre (question to Erik), `Odkaz` in 233/300 (max 18 chars), `PartnerskyKod` in 616/3 206 items.

---------------------------------------------------------------------------------------------------
## 9. Figma
Frames: `W6h Dodací list prijatý – karta (návrh)`, `W6h … (v Money)`, `W6h … Poplatky`, `W6h … Originál + Kontrola`,
`M13b Dodací list – mobil`, `W7b Ponuka – PDF` (place the rendered `offer_sample.png` 1:1 as the page),
`W6g Potvrdenie objednávky – PDF`. Components: `MoneyCardHeader` (label/field grid, group titles in brand blue),
`MoneyField` (states: default, read-only grey, required bold label, error), `MoneySeriesBox`, `MoneyVatRecap`,
`MoneyGrid` (dense 24 px rows, zebra off, numeric right-aligned, column chooser with presets), `MoneyToolbar`,
`PrintPage` (A4 frame for PDF previews). Density: Money is dense — W6h uses 28 px field height and 24 px grid rows
(Smart Mail default 36/40) so the same number of lines fits on screen as in Money.

---------------------------------------------------------------------------------------------------
## 10. Acceptance (Phase 4 for W6h, Phase 6 for offers)
- A warehouse person who knows the Money card finds every field of W6h without help (5 tasks, observed).
- 10 supplier invoices → 10 DL prijaté on TEST: branch centre on header and all items, stock increased in the branch
  warehouse, numbers in the branch series, "Doklad prijatý" equal to the supplier number, read-back equal in 100 %.
- Offer PDF of the fixture overlays the Money original (same positions ± 1 mm) — reviewed by Smart s.r.o.
- Faktúra vystavená attachments are byte-identical to the Money report output (sha256).

---------------------------------------------------------------------------------------------------
## 11. Open questions
For Smart s.r.o. (business decisions — answers go into SETTINGS defaults, no code change):
- **Q-D1** Warehouses and price lists are known (D11, D12). Still open: own numerical series per branch ("DLP NR" =
  Nitra?), whether the centre code always equals the warehouse code (`--branches` shows both), which price list is
  the branch price list ("bez DPH"?) and when warehouse 99 Externý sklad is used.
- ~~Q-D2~~ answered: stock movement date/time = moment of the write to Money (D13).
- ~~Q-D3~~ answered: fees are not handled for now (D14).
- ~~Q-D4~~ answered: returns only in Money (D15).
- ~~Q-D5~~ answered: offers are numbered by Money (D5).
- **Q-D6** Please send the Money print report used for order confirmations (if any) and EN/DE versions of the offer
  report if offers go abroad.
- **Q-D7** Which invoice print reports (SK/EN/DE, zálohová, dobropis) are sent to customers — the implementer gives
  their report ids.
For the Money implementer: MONEY_API §9 questions 1, 2, 8, 9, 10.
