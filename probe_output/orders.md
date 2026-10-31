# Money S4 probe – customer orders (ORDERS_SPEC §19)

Generated: 2026-10-31T13:36:26

## Read-only findings

- **orders**: 200
- **items**: 896
- **Stav**: {"0": 200}
- **Vyrizeno**: {"0": 200}
- **PriznakVyrizeno**: {"True": 77, "False": 123}
- **Storno**: {"0": 200}
- **Faze**: {"1": 200}
- **TypCeny_items**: {"0": 861, "1": 35}
- **orders_with_Odkaz**: 1
- **Odkaz_max_len**: 19
- **orders_with_DatumVyrizeni**: 199
- **orders_with_Obchodnik**: 0
- **orders_with_Osoba**: 0
- **orders_with_DodaciAdresa**: 74
- **items_without_article**: 133
- **items_with_PartnerskyKod**: 1
- **items_with_Rezervovano**: 0
- **items_with_Sleva**: 59
- **items_with_price_list**: 292
- **items_partially_fulfilled**: 0
- **filter_Odkaz_eq_works**: true
- **filter_Poznamka_sw_works**: true
- **delivery_note_items_linked_to_order_items**: {"notes": 100, "items_with_source": 11, "matching_order_items": 0}
- **TransportTypes**: [{"Kod": "P10", "Nazev": "DPD_TN"}, {"Kod": "P4", "Nazev": "Packeta HD"}, {"Kod": "P", "Nazev": "DPD"}, {"Kod": "P5", "Nazev": "Packeta PP"}, {"Kod": "P3", "Nazev": "Packeta BOX"}, {"Kod": "1", "Nazev": "Geis Parcel"}, {"Kod": "D", "Nazev": "Dobierka"}, {"Kod": "P9", "Nazev": "DPD_TT"}, {"Kod": "P1", "Nazev": "Čaká sa na platbu"}, {"Kod": "P6", "Nazev": "Prepravnou službou"}, {"Kod": "P8", "Nazev": "DPD_NR"}, {"Kod": "P2", "Nazev": "Platba bola zrealizovaná"}, {"Kod": "0", "Nazev": "Geis Cargo"}, {"Kod": "P11", "Nazev": "DPD_SE"}, {"Kod": "O", "Nazev": "Osobný odber"}, {"Kod": "P7", "Nazev": "Packeta"}]
- **PaymentTypes**: [{"Kod": "K", "Nazev": "Uskutočnená kreditná transakcia"}, {"Kod": "X", "Nazev": "NEZAPLATENE"}, {"Kod": "P1", "Nazev": "Čaká sa na platbu"}, {"Kod": "P3", "Nazev": "Platobnou branou Gopay"}, {"Kod": "C", "Nazev": "Platba šekom"}, {"Kod": "P2", "Nazev": "Platba bola zrealizovaná"}, {"Kod": "O2", "Nazev": "Platobnou kartou na predajni"}, {"Kod": "H", "Nazev": "V hotovosti"}, {"Kod": "P", "Nazev": "Platobnou kartou"}, {"Kod": "D", "Nazev": "Dobierkou"}, {"Kod": "S", "Nazev": "Poštovou poukážkou"}, {"Kod": "O1", "Nazev": "ON-Line - čaká na schválenie"}, {"Kod": "B", "Nazev": "Bankovým prevodom"}, {"Kod": "Z", "Nazev": "Zápočtom"}, {"Kod": "I", "Nazev": "Inkasom"}]
- **ArticleUnits_DesetinnaMista**: {"('ks', 0.0)": 266, "('bal', 0.0)": 33, "('kg', 3.0)": 1}
- **ArticleUnits_with_NedelitelneMnozstvi**: 34
- **test_company_has_discount**: false
- **ProdejniCeny**: {"rows": 0, "TypCeny": {}, "with_MnozstevniSleva": 0, "MnozstevniSleva_shapes": [], "with_Sleva": 0, "inactive": 0}

## Write test

- not run (use --orders --allow-write-test on the TEST agenda)

Give this file to Claude Code / Cursor before implementing customer orders (Phase 4).
