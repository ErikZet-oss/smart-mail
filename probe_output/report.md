# Money S4 API probe report

Generated: 2026-10-31T14:23:09

| Step | Result | Note |
|---|---|---|
| token | OK | token from http://localhost:81/connect/token (form) |
| GraphQL schema GET /graphql/schema | OK | HTTP 200; IssuedOffer (ponuky) in schema: False |
| GraphQL { Version } | OK | API version 1.15.11.7730 |
| GraphQL filters (eq/ct/sw/ew, date formats, OR) | OK | eq:1, ct:10, sw:50, ew:2, date_iso:33, date_sk:33, date_iso_time:33, or:1 |
| ArticleSuppliers (kódy dodávateľov) | OK | 50 rows, 50 with DodavatelskyKod, Parent_ID = article: True |
| WarehouseStocks (zásoby) | OK | 5 rows, errors: False |
| ProdejniCeny (ceny zákazníka) | FAILED | 0 prices in 55 ms, errors: none |
| ReceivedDeliveryNotes (dodacie listy prijaté) | OK | 5 notes, 39/39 items with article |
| ReceivedInvoices items (link to delivery note / stock) | OK | 0/309 items linked to a source item, 305 with article (evidence for Mode A/B) |
| smoke GET REST /IssuedInvoice/0/1 | OK | HTTP 200, 118 ms |
| default page limit (GET /IssuedInvoice without paging) | OK | returned 1000 items in 6683 ms (likely DefaultPageLimit if this is a round number) |
| resource access (rights of the API role) | OK | all readable |
| probe invoice found by paging | OK | 37261473 |
| filter syntax | FAILED | no syntax returned only the probe invoice - see report.json |
| text search ?text=&propertyName=CisloDokladu | FAILED | 0 results, probe invoice found: False |
| Properties projection | OK | keys per row [214, 214, 225], non-empty [88, 88, 122] (small numbers = projection works) |
| OrderProperties (DatumVystaveni, Direction=1) | OK | Direction=1 gives unclear order |
| GET /IssuedInvoice/{id} detail | OK | items: 1, attachmentsList: 0 |
| PDF report GET /IssuedInvoice/{id}/Report/{reportId} | OK | HTTP 200, application/octet-stream, PDF ok in 5143 ms |
| article search (text on Kod/Katalog/Nazev) | OK | Kod: 0, Katalog: 1, Nazev: 0 |
| received invoices: template fields present | OK | 5 sample rows; filled counts {'puvodniDoklad': 2, 'variabilniSymbol': 5, 'bankovniSpojeniIBAN': 4, 'firma_ID': 4, 'ciselnaRada_ID': 5, 'druhDokladu_ID': 5, 'predkontace_ID': 5, 'cleneniDPH_ID': 5, 'mena_ID': 5, 'stredisko_ID': 4, 'zakazka_ID': 0, 'cinnost_ID': 0, 'zpusobPlatby_ID': 1} |

Full details: report.json (field names and types only, unless --show-values was used).
