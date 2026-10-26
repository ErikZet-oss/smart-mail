# FIGMA.md — how to design Smart Mail in Figma

Use this file in two ways:
- **Designer in Figma**: follow sections 1–7 to build the file (foundations → components → screens → prototype).
- **Figma Make / Figma AI / another AI design tool**: paste section 8 ("One-shot prompt") — it is self-contained.
The detailed source of truth is `docs/UX_SPEC.md` (tokens, components, screens) and `docs/PRODUCT_SPEC.md` (features).
All UI text in Slovak. Roundcube users must recognise the structure immediately.

---------------------------------------------------------------------------------------------------
## Status (v2.10): the Figma file is DONE — https://www.figma.com/design/vBDv8OCQTjxPBMzq6KBcHU
355 frames (308 web, 47 mobile), ≈ 250 components with variants, variables Color (Light/Dark) and Size, flows 0–6 + 4b
wired as prototypes. `docs/FIGMA_MAP.md` lists every frame with its node id. The 9 contradictions found while drawing
are closed in DECISIONS D23. Open for the designer: place the 8 Roundcube PNGs on page 08 (placeholders `92:52`…`92:94`);
from now on change the look in Figma first, then tell the coding agent the frame link. The sections below are the
brief the file was built from.

## 0. Readiness — what is ready for the visual design (brief; all done)
| Input | Status | Where |
|---|---|---|
| Every screen, subpage, dialog and state (web + mobile), with IDs, routes, content and states | ready | `docs/SCREENS_SPEC.md` (≈ 60 web screens/dialogs, G1–G7 shell, 18 mobile screens, E1–E4 e-mails) |
| Every settings section and field (control, default, help text) | ready | `docs/SETTINGS_SPEC.md` (20 sections, frames W12-01…W12-20) |
| Tokens: colours light/dark, type, spacing, radius, shadows, layout, component sizes | ready, importable | `design/tokens.json` (Tokens Studio / variables import), `design/tokens.css`, UX_SPEC §2 |
| Contrast check (WCAG AA) of all token pairs | ready | `design/CONTRAST.md` (generated, all pass) |
| Components with variants and states; component sizes; status colours; icon map | ready | UX_SPEC §2.6–2.8, §3 |
| Content of every AI card type | ready | UX_SPEC §3.1 |
| Money look-alike screens and print documents (exact layout) | ready | DOCUMENTS_SPEC §2, §4, §9; `fixtures/documents/*.png` |
| Sample content (fictional companies, e-mails, documents, branch Senica, Money warehouses and price lists) | ready | §7 |
| Slovak UI wording (Roundcube SK labels + microcopy) | ready | PRODUCT_SPEC §1, UX_SPEC §7, SCREENS_SPEC |
| Prototype flows | ready | §6 |
| Logo (new, blue `#0F75BC`, vector original) | ready: SVG blue/white + PNG | `design/brand/`, UX_SPEC §2.9 |
| App icon (PWA 192/512, maskable, Apple touch) and favicon "S" | ready (generated from the vector, `make_icons.py`); the designer may refine | `design/brand/app-icon/` |
| Screenshots of the customer's Roundcube (login, inbox, message, list options, compose, settings, Priečinky, Nastavenia e-mail schránky) | ready, anonymised — **the look to mirror** (D19) | `design/reference/roundcube/` 01–08, UX_SPEC W1, W2, W2o, W4, W12 |
| Signature editor (HTML + source code + images), provider settings, filter folders | decided (D20–D22) | DECISIONS, SETTINGS 02, 03a, 09b, 11a, 11c |
| Offer editor details | decided: no packaging rounding (D17), stock of all warehouses and all price lists shown (D18) | DECISIONS |

### 0.1 Order of work (follows the build phases, so developers always have the next screens ready)
1. **Foundations** — import `design/tokens.json`, text styles, icons (Lucide), logo SVG, app icons, grids; check
   light/dark; put the 8 Roundcube screenshots on a page `08 Roundcube reference` next to the frames that mirror them.
2. **Core components** — Button, Input, Select, Chip, Badge, Avatar, Tabs, Menu, Toast, Banner, Dialog, Drawer,
   ToolbarButton, RailItem, FolderItem, MessageRow, EmptyState, Skeleton.
3. **Phase 1 – mail like Roundcube**: G1–G7, W1, W1a–c, W1b + W2b, W2 (+ states), W2o, W2c, W2e, W2i–W2n, W4 (+ W4b–f),
   W9, W10, W11, W12 shell + W12-01…06, W12-09b, 09…12, `HtmlSignatureEditor` (all states), W13–W17, W15b; mobile M0–M4, M8, M9, M15, M18. → **review with the team:
   "do I find everything like in Roundcube?"**
4. **Phase 2/5 – AI**: AiSuggestionCard gallery (13 types × states), W3, W3b, W5, W5b, W14, W12-07, W12-17, W12-08;
   M5, M6, M16, M17; e-mail E3.
5. **Phase 3/4 – documents**: Money look-alike set, W6 hub, W6e, W6h (+ states), W6u, W6f/W6g, W8, W8d, W8b, W8c, W9a,
   W9b, W12-13…15; M10, M12, M13, M13b; e-mails E1, E2, E4.
6. **Phase 6 – offers**: W7, W7a, W7b, W12-16, W12-18, M14 (after the open offer questions are answered).
7. **Finish**: W12-19, W12-20, tablet T1, dark check, prototype flows, Dev Mode annotations, handoff page.
Rough size: ≈ 250 frames (≈ 60 web IDs × default/loading/empty/error, 20 settings sections with sub-frames, 18 mobile
screens with variants, 4 e-mails).

---------------------------------------------------------------------------------------------------
## 1. File structure (pages)
1. `00 Cover` — name, version, status legend (🟡 WIP, 🟢 Ready for dev, 🔵 In dev).
2. `01 Foundations` — color variables (Light/Dark), type styles, spacing/radius, elevation, icons, grids, logo, app icon.
3. `02 Components` — atoms → molecules → organisms (section 4), each on its own frame with all variants.
4. `03 Patterns` — AI card states gallery, checks, toasts & banners, empty states, forms.
5. `04 Web` — all screens of SCREENS_SPEC §1 + settings W12-01…W12-20 (section 5) at 1440 × 900 (+ key screens at
   1280 and 1920).
6. `05 Mobile` — screens M0–M18 at 390 × 844 (+ M1/M3 at 360 × 780).
7. `06 Flows` — prototype flows (section 6).
8. `07 Handoff` — redlines for tricky layouts, keyboard map, copy table, changelog.
9. `08 Roundcube reference` — the 8 anonymised screenshots from `design/reference/roundcube/` (do not edit).
10. `99 Archive` — old explorations.

---------------------------------------------------------------------------------------------------
## 2. Variables & styles
- **Import `design/tokens.json`** (Tokens Studio plugin, or a "variables import" plugin that reads W3C design tokens)
  instead of typing values — the same file generates the CSS for the code, so Figma and code cannot drift.
- **Collection `Color`** with modes `Light` and `Dark`; names exactly as tokens in UX_SPEC §2.1
  (`bg/canvas`, `text/secondary`, `brand/primary-600`, `ai/50`, `cat/supplier_document` …). Scope fills/strokes/text
  correctly. Brand blue = logo blue `#0F75BC`.
- **Collection `Size`**: `space/2…48`, `radius/xs…lg`, `layout/rail 72`, `layout/folders 232`, `layout/list 360`,
  `layout/assistant 380`, `layout/appbar 56`, `layout/bottomnav 64`.
- **Text styles** (Inter): display, title, heading, body-lg, body, body-strong, label, small, caption, micro — sizes in
  UX_SPEC §2.3; enable tabular numbers on `small`/`caption` variants named `…/tnum`.
- **Effect styles**: `e1`, `e2`, `e3`; `focus-ring` (2 px `brand/primary-500`, offset 2).
- **Icons**: Lucide (Figma community "Lucide Icons"), 20 px frame, stroke 1.75; create component `Icon` with instance
  swap property; which icon where: UX_SPEC §2.8.
- **Logo**: `design/brand/logo-smart.png` / `logo-smart-white.png` (replace with the vector original when it arrives);
  usage rules UX_SPEC §2.9.
- **Grids**: Desktop 1440 — fixed columns via layout frames (rail 72 / folders 232 / list 360 / fluid / panel 380);
  Mobile — 4 columns, 16 margin, 8 gutter; 4-pt baseline nudge.

---------------------------------------------------------------------------------------------------
## 3. Building rules
- Auto layout everywhere; no absolute positioning except overlays. Hug/fill set intentionally.
- Component properties: `variant` for kinds/states, `boolean` for optional parts (icon, badge, checkbox), `text` for
  labels, `instance swap` for icons/avatars.
- Name layers like code: `MessageRow / compact / unread`, `AiSuggestionCard / invoice_attach / ready`.
- Every interactive component has: Default, Hover, Pressed/Active, Focus, Disabled (+ Loading, Error where relevant).
- Use realistic Slovak content (section 7), never lorem ipsum; long names and long subjects must be tested (truncate
  with ellipsis, tooltip).
- Dark mode: check every screen by switching the variable mode, don't draw separate dark screens except W2 + M1 + M3.

---------------------------------------------------------------------------------------------------
## 4. Components to build (with properties)
Atoms: `Button` (kind: primary/secondary/ghost/danger/ai; size: sm/md/lg; icon: none/left/right/only; state),
`IconButton`, `ToolbarButton` (icon 20 + micro label under; caret: bool; state), `RailItem` (icon, label, badge, active,
compose: bool), `Input`, `Textarea`, `Select`, `Checkbox`, `Radio`, `Switch`, `SegmentedControl`, `Chip` (category /
filter / status / source), `Badge` (count/dot), `Avatar` (initials/photo/logo; size 20/28/32/40), `Tooltip`, `Divider`,
`Skeleton` (row/card/text), `ProgressBar` (quota, confidence).
Molecules: `SearchField` (scope + chips), `RecipientCombobox` (chips with company tag), `FolderItem` (depth 0–2,
count, active, drag-over), `CategoryItem`, `MessageRow` (density: compact/comfortable × state: read/unread/selected/
multi-selected/hover × flags: attachment, flagged, ai-ready, assigned, urgent, replied), `AttachmentChip` (type,
state: default/scanning/infected), `CheckRow` (ok/warn/fail/info, with action link), `DocumentFieldRow` (status,
confidence, source page), `OfferLineRow` (match: exact/equivalent/ambiguous/none; price source: money/history/manual),
`ItemMatchRow` (method: supplier-code/learned/ean/our-code/order/ai/unmatched/non-stock; state),
`OrderLineRow` (method: offer/our-code/learned-customer-code/money-code/ean/catalog/history/ai/unmatched/text;
state: matched/confirm/unmatched/text/dropped (no stock, no rounding — DECISIONS D6);
price: list/offer/manual/customer-diff), `OrderHeaderPanel` (blocks with normal/warning/blocked), `RuleList`, `PersonTile` (default/hover/selected/inactive; manager badge; last-used ring), `PersonChip` (full/compact; open), `SignatureBlock` (default/hover/
edited/outdated),
`Toast` (info/success-undo/error-retry), `Banner` (info/warning/danger/ai), `SecurityBanner` (phishing/iban/dmarc/
first-time), `QuickActionChip`, `Menu`, `Popover`, `Tabs`, `Pagination`.
Organisms: `Rail`, `FolderColumn`, `MessageList` (header + search + filters + rows), `Toolbar` (Roundcube order: Odpovedať,
Odpovedať všetkým ▾, Poslať ďalej ▾, Vymazať, Nevyžiadané, Označiť, Viac | Prideliť, Vybavené, ✦ Asistent),
`MessageView`, `AiSuggestionCard` (type × state — content per type in UX_SPEC §3.1; on `03 Patterns` build all 13
types in the ready state + the 7 states on `reply` and `order_create`), `AssistantPanel` (tabs Asistent/Zákazník; messages: user/assistant/tool-call/proposal), `CustomerCard`,
`ComposeForm`, `ComposeAiPanel`, `PdfViewer`, `DataTable`, `CommandPalette`, `SettingsLayout`, `AutonomyMatrix`,
`AppBar` (mobile), `BottomNav`, `BottomSheet`, `SwipeRow`, `Dialog`, `Drawer`, `EmptyState`.
**Money look-alike set** (DOCUMENTS_SPEC §9; used only on W6h and in PDF previews — copy of the Money card, dense):
`MoneyCardHeader` (2 label/field columns + group titles "Dátum" / "Podrobnosti" in brand blue, right block with
sub-tabs Dodávateľ / Kon. príjemca / Fakt. adresa), `MoneyField` (default / read-only grey / required = bold label /
error / with "…" picker and ✕ clear like Money), `MoneySeriesBox` (number + series e.g. "DLP SE"), `MoneyVatRecap`
(rows Nulová 0 % / Znížená 5 % / Znížená 19 % / Základná 23 % × Základ / DPH / Vrátane DPH + currency + V domácej
mene), `MoneyToolbar` (Opraviť, Opraviť hromadne, Pridať výberom, Zmazať, Excel, Σ, Legenda, Nahor, Dolu),
`MoneyGrid` (24 px rows, Money column order, numbers right-aligned with 4/2 decimals, status column, column chooser
with presets "Kontrola príjmu" / "Ako v Money"), `PrintPage` (A4 frame for PDF previews).

---------------------------------------------------------------------------------------------------
## 5. Screens to design (frame names)
**Source of truth for the frame list: `docs/SCREENS_SPEC.md` §1 (web), §13 (mobile) and `docs/SETTINGS_SPEC.md`
(settings).** Frame name = `<ID> <Title>` (e.g. `W6f Kontrola objednávky`); one frame per state listed in the
screen's "States" (at least default, loading, empty, error). Pages and grouping in Figma:

| Figma page section | Frames |
|---|---|
| Prístup | W1 Prihlásenie (+ chyby, rate limit), W1a 2FA, W1b Kto ste? (+ posledná osoba; bez PIN-u), W1c Heslo sa zmenilo / relácia vypršala |
| Shell | G1 Rail (all badges, bottom items, TEST pill), G2 Column headers (no global top bar; page header variants), G3 Folder column (+ ⋮ menu, context menu, quota %, Money dot), G4 Toasts, G5 Dialog patterns, G6 Banners (6), G7 Drop zone, W2b PersonChip popover |
| E-mail | W2 Doručená pošta (+ nič nevybraté with logo watermark, prázdny priečinok, Klasické zobrazenie, Konverzácie, tmavý režim, výber s checkboxmi), W2o Nastavenia zoznamu, W2c Vlákno (+ AI karta žiadosť o faktúru, príjem tovaru, objednávka; presence banner; interné poznámky), W2e Hromadné akcie, W2f AI kategória, W2g Moje (4 views), W2h Všetky schránky, W2i Odložiť, W2j Prideliť / Odovzdať, W2k Bezpečnostné varovanie, W2l Náhľad prílohy, W2m Tlač, W2n Zdroj |
| Písanie | W4 Písanie (+ AI panel, + „Odpovedá“ prepnutie, + undo toast, + chyba odoslania), W4b Kontrola pred odoslaním, W4c Naplánovať, W4d Odpovede, W4e Podpis pre túto správu, W4f Vyskakovacie okno |
| Asistent | W3 Asistent (+ tool cards, návrh, história, vypnutý), W3b Zákazník (+ nespárovaný) |
| Dnes | W5 Dnes (+ prázdny deň), W5b Prehľad pobočky |
| Doklady | W6 hub tabs (Dodacie listy, Objednávky, Ponuky, Reklamácie, Upomienky — bez faktúr prijatých), W6e Dodacie listy – zoznam, **W6h Dodací list prijatý – karta ako v Money** (návrh, chýbajú údaje, v Money, Poplatky, Originál + Kontrola), W6f Kontrola objednávky (+ variants of ORDERS states), W6g Objednávka vytvorená (+ PDF Potvrdenie objednávky), W6u Nahrať doklad, W7 Ponuky – zoznam, W7a Editor, W7b PDF (vložte 1:1 obrázok `fixtures/documents/offer_sample.png` – je to presná kópia zostavy Money), W8 Objednávky – zoznam, W8d Zmena objednávky, W8b Upomienky (+ kontrola pred odoslaním), W8c Reklamácie (zoznam + detail), **E1 Potvrdenie objednávky, E2 Upomienka, E3 Ranný prehľad, E4 Otázka k objednávke** (HTML e-maily, 640 px – SCREENS_SPEC E1–E4) |
| Kontakty | W9 Kontakty (+ Money adresár, import), W9a Zákazník 360 (6 tabs), W9b Firma – Objednávky |
| Hľadanie | W10 Výsledky (+ prázdne), W11 Paleta príkazov |
| Nastavenia | W12 shell (+ hľadanie v nastaveniach, neuložené zmeny, konflikt 409), W12-01 Nastavenia (subsections a–e), W12-02 Priečinky (zoznam s prepínačmi odoberania, kvóta), W12-03a Identity (+ HTML podpis: WYSIWYG, Zdrojový kód, Vložiť obrázok), W12-03b Môj profil, W12-04 Odpovede, W12-05 Filtre, W12-06 Mimo kancelárie, W12-09b Nastavenia e-mail schránky (info + tlačidlo k poskytovateľovi), W12-07 AI asistent (matica), W12-08 Notifikácie, W12-09 Bezpečnosť, W12-10 Používatelia a role, W12-11a–e Pobočky a osoby (Údaje, Osoby + drawer, Podpis s náhľadom a zdrojovým kódom, Priečinky pobočky, Prihlasovanie, Money: stredisko, cenník, sklad, rady), W12-12 Schránky (+ test pripojenia), W12-13a–f Money S4, W12-14 Nákup a sklad, W12-15 Objednávky, W12-16 Katalóg a ceny, W12-17a–f AI – správa, W12-18 Knižnica, W12-19 Audit log, W12-20 Systém |
| Systém | W13 Úvodná prehliadka (6 krokov), W14 Notifikácie, W15 Klávesové skratky, W15b O systéme, W16a 403, W16b 404, W16c 500, W16d Offline, W17 Údržba |
| Tablet | T1 E-mail (1024 × 768, folders drawer, assistant overlay) |
| Mobile (390 × 844) | M0 Kto ste?, M1 Zoznam (+ swipe, multi-select), M2 Priečinky, M3 Detail + AI karta (+ schválené), M4 Písanie, M5 Asistent (half/full), M6 Dnes (+ Pobočka), M8 Hľadanie, M9 Nastavenia (zoznam + 3 sekcie), M10 Zákazník, M11 Push notifikácie, M12 Objednávka – kontrola (+ bottom sheet), M13 Doklady, M13b Dodací list prijatý, M14 Ponuka, M15 Kontakty, M16 Notifikácie, M17 AI pri písaní, M18 Viac |

Each frame gets a Dev Mode annotation with its route from SCREENS_SPEC §1 and, for settings, the field ids from
SETTINGS_SPEC (e.g. `prefs.list.density`).

---------------------------------------------------------------------------------------------------
## 6. Prototype flows (page `06 Flows`)
1. **Invoice request**: W2 select row → AI card ready (checks ✓) → Schváliť a odoslať → toast "Správa odoslaná · Späť"
   → row moves to Vybavené.
2. **Goods from a supplier**: W2c supplier e-mail with invoice PDF → AI card "Príjem tovaru · 8 položiek" → W6h
   (Money-like card) → 7 green, 1 amber → open drawer, confirm article, "Zapamätať" → `Vytvoriť v Money` → Dodací list
   prijatý with the Money number, read-back ✓, "Vrátiť" countdown. (No received invoice — D7.)
3. **Assistant task**: Ctrl+J → type "Pošli ABC Stav neuhradené faktúry" → tool cards → proposal card → Schváliť.
4. **Offer from inquiry**: inquiry e-mail → AI card "Pripraviť ponuku" → W7 editor (pick alternative article; quantity stays as requested, package info only)
   → `Vytvoriť ponuku v Money` (Money number PV…) → Odoslať e-mailom → W4 with PDF attached.
0. **Branch login**: W1 (senica@smartsro.sk) → W1b click "Jana Nováková" → W2 (PersonChip "Jana") → Odpovedať →
   W4 shows "Odpovedá: Jana Nováková" and Jana's signature → switch to "Peter" in the chip → signature hint → Odoslať.
4b. **Customer order from PDF**: W2 order e-mail (AI card "Objednávka od Stavmont a.s. · 6 položiek") →
   `Skontrolovať objednávku` → W6f: 4 green, 1 amber (equivalent ISO 4032 → confirm), 1 unmatched (pick article or
   "Opýtať sa zákazníka") → `Vytvoriť objednávku v Money` → created + read-back ✓ →
   `Otvoriť návrh potvrdenia` → W2 with confirmation draft (table + "Zmeny oproti objednávke") → Schváliť a odoslať.
5. **Mobile morning**: M6 Dnes → batch approve 3 → M1 → swipe Vybavené → M3 → Odpovedať.
6. **Roundcube user first login**: W13 tour 5 steps.

---------------------------------------------------------------------------------------------------
## 7. Sample content (use consistently)
Company: Smart s.r.o. (spojovací materiál). Users (fictional): Peter Hudák (admin, vedúci pobočky), Jana Nováková (obchod), Eva (účtovníctvo).
Branches (= Money warehouses, DECISIONS D4, D11): 10 Trnava, 20 Senica, 30 Nitra, 40 Trenčín; warehouse dropdowns also
list 99 Externý sklad (never a branch). Price list dropdown (D12, `Kód – Názov`): 10-bez DPH – Trnava bez DPH,
10-s DPH – Trnava s DPH, 13 – PKT, 20-bez DPH – Senica bez DPH, 20-s DPH – Senica s DPH, 30-bez DPH – Nitra bez DPH,
30-s DPH – Nitra s DPH, 40-bez DPH – Trenčín bez DPH, 40-s DPH – Trenčín s DPH, 99 – Externý sklad, A1 - 100% – 100%,
A2 - 70% – 70%, A3 - 30% – 30%, MPC – Minimálny predajný cenník. Senica uses "20-bez DPH – Senica bez DPH".
BranchChip: full "Pobočka Senica · Stredisko 20 · Cenník 20-bez DPH · Sklad 20" (page headers W6h/W6f/W7a/W8c), short "Pobočka Senica · stredisko 20 · sklad 20" (lists, cards).
Branch "Pobočka Senica" (senica@smartsro.sk, shared login, sklad 20): Peter Hudák (vedúci pobočky), Jana Nováková
(obchod), Marek Kováč (sklad) — fictional people; real names are entered by the customer in Settings. Signature:
"S pozdravom / {meno} / {funkcia} · {mobil} / Smart s.r.o. – pobočka Senica · [adresa pobočky] · [telefón pobočky]" (use placeholder phone numbers like +421 900 000 000).
Mailboxes: eshop@smartsro.sk, info@smartsro.sk, senica@smartsro.sk, nitra@smartsro.sk. Folders of the shared mailbox
(as in the customer's Roundcube): Doručená pošta 5 220, Koncepty, Odoslané, Nevyžiadaná pošta 4, Kôš 1, Archív,
Dodávatelia 39, Faktúry 17, Kurier 42, Nitra, Senica 6 484, Smart, Trenčín 3 653; quota 92 % (red). List footer
"Správy: 1 – 50, z 30 163". Dates like Roundcube: "Dnes 09:40", "Ne 17:20", "Pi 14:14".
Messages:
| Odosielateľ | Firma | Predmet | Kategória | AI zhrnutie |
|---|---|---|---|---|
| Ján Novák | ABC Stav s.r.o. | Kópia faktúry 2026123 | Žiadosť o faktúru | Žiada kópiu FA – nájdená v Money |
| Peter Hudec | Kovo Trnava s.r.o. | Cenová ponuka M10x30 A2 | Dopyt | 5 000 ks DIN 933 A2, termín do piatku |
| fakturacia@fixtech.cz | Fixtech CZ s.r.o. | Faktura 2611452 | Doklady dodávateľov | 8 položiek → dodací list prijatý, prenesenie DP |
| Martin Kráľ | Stavmont a.s. | Reklamácia – podložky M12 | Reklamácia | Dodané podložky nesedia s objednávkou (urgentné) |
| noreply@kurier-express.sk | — | Zásielka 0123456 doručená | Doprava | Objednávka OP263100 doručená |
| Klaus Weber | Schrauben Weber GmbH | Anfrage DIN 912 M8x25 12.9 | Dopyt | 2 000 ks ISO 4762 M8x25 12.9, nemčina |
| Lucia Beňová | Elektro Beňo s.r.o. | Atest 3.1 k dodávke | Žiadosť o dokument | Potrebuje inšpekčný certifikát k FV2026/0140 |
| obchod@novinky.sk | — | Jesenné novinky | Feed | — |
Invoice: FV2026/0123, ABC Stav s.r.o., 1 234,50 €, vystavená 15. 9. 2026, splatná 14. 10. 2026, uhradená.
Overdue: FV2026/0101 (412,80 €, 12 dní po splatnosti). Order: OP263100 (vybavená).
Article: Skrutka DIN 933 M10x30 A2 (ekv. ISO 4017), balenie 200 ks, posledná cena pre Kovo Trnava 0,084 €/ks.
Supplier invoice lines (Fixtech CZ, FA 2611452): "FX-933-1030-A2 Šroub ISO 4017 M10x30 A2, 25 bal à 200" → Skrutka DIN
933 M10x30 A2 (Kód dodávateľa); "4006209123456 Matice M10 A2" → Matica ISO 4032 M10 A2 (EAN); "Podložka 10,5 nerez"
→ Podložka DIN 125 M10 A2 (Návrh AI – potvrdiť).
Received delivery note W6h (all fictional): Fixtech CZ s.r.o., IČO 27654321, DIČ CZ27654321, Doklad prijatý
DL-2026-04417, Párovací symbol 2611452, rad "DLP SE", stredisko 20, sklad 20, Predkontácia FP010, Druh pohybu
obstaranie, Druh skl. pohybu príjem, Vystavenie 20. 10. 2026, Sklad. pohybu "pri zápise do Money" (after create
21. 10. 2026 09:14 — D13), prenesenie DP (23 %,
DPH 0,00); lines e.g. 1 · skr. M10 x30 A2 DIN 933 · Katalóg 309903010030 · Kód dodávateľa FX-933-1030-A2 · 30 ·
5 000,0000 ks · 23,00 · Iba základ · 0,0612 · 306,00 · tovar; 2 · mat. M10 A2 ISO 4032 · 311403210000 · FX-4032-10-A2 ·
2 000,0000 ks · 0,0205; 3 · podl. M10 A2 DIN 125A · 311712510000 · 4006209123457 (EAN) · 2 000,0000 ks · 0,0071 (amber:
"Návrh AI – potvrdiť"); Poplatky: Doprava 12,00 € – read-only, "nezapisuje sa" (D14).
Offer PDF: `fixtures/documents/offer_sample.json` (Kovo Trnava s.r.o., Money number PV263412, 897,90 €).
Customer order (Stavmont a.s., e-mail from Martin Kráľ to objednavky@smartsro.sk, attachment Objednavka_PO-45821.pdf,
požadovaný termín 12. 11. 2026, dodať na stavbu "Bytový dom Nivy, Mlynské nivy 12, Bratislava"):
| # | Zákazník napísal | Náš artikel | Metóda | Množstvo | Cena/ks |
|---|---|---|---|---|---|
| 1 | SM-933-1030 Skrutka 6hr M10x30 A2 | Skrutka DIN 933 M10x30 A2 | Naučený kód zákazníka | 2 000 ks | 0,0790 € |
| 2 | Matica M10 A2 DIN 934 | Matica ISO 4032 M10 A2 | Ekvivalent – potvrdiť | 2 000 ks | 0,0310 € |
| 3 | Podložka 10,5 DIN 125 A2 | Podložka DIN 125 M10 A2 | Náš kód | 2 450 ks (zapíše sa presne, bez zaokrúhlenia) | 0,0120 € |
| 4 | Kotva M10x90 pozink | Kotva klinová M10x90 Zn | Z histórie | 300 ks | 0,4100 € |
| 5 | 4006209654321 | Skrutka DIN 912 M8x25 12.9 | EAN | 500 ks | 0,0640 € |
| 6 | Hmoždinka 8 mm "ako minule" | — | Nespárované | 1 000 ks | — |
No stock column and no rounding (D6). Warnings: W8 (iná dodacia adresa); credit 18 200 € z 25 000 €; po splatnosti 0 €.

---------------------------------------------------------------------------------------------------
## 8. One-shot prompt (for Figma Make / AI design tools)

```
Design a responsive web app UI (desktop 1440×900 and mobile 390×844) called "Smart Mail": the company e-mail client
of a Slovak fastener e-shop (company logo: blue wordmark "SMART", colour #0F75BC — use it white at the top of the rail
and blue on the login screen). ALL UI TEXT IN SLOVAK. Employees come from Roundcube webmail (Elastic skin), so keep its
structure and wording:
- Mirror the company's current Roundcube (Elastic skin): no bar across the top; every column has its own header.
- Dark left rail (72 px, #1F2937) with the white SMART logo on top and icon + small label under each: "Vytvoriť
  správu" (blue #0F75BC icon and blue label, not a filled button),
  "E-mail" (active), "Dnes", "Doklady", "Kontakty", "Nastavenia"; bottom: sparkle icon "Asistent", bell, person
  avatar "Jana", then "Tmavý režim" (moon), "O systéme" (?), "Odhlásiť" (red power icon).
- Folder column (232 px, #F6F8FA): header "eshop@smartsro.sk" + ⋮; folders with icons and blue count pills
  "Doručená pošta 5220", "Koncepty" (pencil), "Odoslané" (paper plane), "Nevyžiadaná pošta 4" (flame), "Kôš 1",
  "Archív", "Dodávatelia 39", "Faktúry 17", "Kurier 42", "Senica 6484"; section "AI TRIEDENIE" with colored dots: Dopyty 12 (#E8590C),
  Objednávky 4 (#2B8A3E), Žiadosti o faktúru 3 (#1C7ED6), Doklady dodávateľov 5 (#C2255C), Reklamácie 1 (#E03131),
  Doprava 2 (#0C8599), Platby 1 (#66A80F), Žiadosti o dokument 1 (#F08C00), Feed 18 (#868E96); section "MOJE":
  Pridelené mne, Čakám na odpoveď, Odložené; bottom: drive icon + quota bar + "92 %" (red).
- Message list (360 px): header toolbar with icon + label under: "Výber", "Konverzácie", "Možnosti", "Obnoviť"; search
  field "Vyhľadať…" with envelope + caret; chips Všetko/Neprečítané/Označené/S prílohou/Nevybavené; two-line rows like
  Roundcube (line 1 sender small grey + "Dnes 09:40" right; line 2 yellow dot for unread + bold subject + paperclip),
  then a grey one-line AI summary and a category chip; footer "« ‹ Správy: 1 – 50, z 30163 [1] › »".
- Reading pane: Roundcube toolbar with icon + label under: Odpovedať, Odpovedať všetkým ▾, Poslať ďalej ▾, Vymazať,
  Nevyžiadané, Označiť, Viac; right after a divider: Prideliť, Vybavené, "✦ Asistent". Header like Roundcube: avatar,
  Od / Komu / Dátum, links "Zhrnutie · Hlavičky · Čistý text", attachment chip with size. Subject "Re: Kópia faktúry
  2026123", sender "Ján Novák <novak@abcstav.sk>" with company chip "ABC Stav s.r.o.".
- Under the header an AI suggestion card (violet #5B4CDB accent, background #F3F1FE, 12 px radius) titled "Návrh AI ·
  Žiadosť o faktúru" with green check rows: "Nájdené v Money: FV2026/0123 · 1 234,50 € · uhradená", "Odberateľ =
  ABC Stav s.r.o. (firma odosielateľa)", "PDF z Money priložené"; attachment chip "Faktura_FV2026-0123.pdf"; a white
  draft preview "Dobrý deň, pán Novák, v prílohe Vám posielame kópiu faktúry FV2026/0123. S pozdravom"; buttons
  "Schváliť a odoslať" (blue #0F75BC primary), "Upraviť", "Zamietnuť"; small grey footer "Návrh AI – nič sa neodošle ani
  nezapíše bez vášho schválenia".
- Optional right panel (380 px) "Asistent" with tabs "Asistent" / "Zákazník": chat with tool-call cards ("Hľadám v
  Money… 2 neuhradené faktúry") and a customer card (IČO, otvorené faktúry 3 · 4 210 €, po splatnosti 1 · 12 dní,
  posledné objednávky).
Also design: "Dnes" dashboard (greeting "Dobré ráno, Jana", AI summary, KPI cards, list "Na schválenie" with button
"Schváliť všetky bezpečné (3)"); received delivery note "Dodací list prijatý" that copies the Money card (dense label/field grid,
groups Dátum / Podrobnosti, supplier block, VAT recap, item grid Poradie · Názov · Katalóg · Kód dodávateľa · Kód
skladu · Počet MJ · MJ · Sadzba DPH · Typ ceny · Jedn. cena · Celková cena, primary "Vytvoriť v Money");
customer order review "Kontrola objednávky" (order PDF left with highlighted lines; right: customer block with
credit bar and discount, PO number PO-45821, delivery address badge "iná ako v karte", lines customer text → our article
with method chips "Naučený kód zákazníka", "Ekvivalent – potvrdiť", "Nespárované", quantity "2 450 ks", price
"0,0790 € · cenník zákazníka −12 %" (no stock, no rounding), rule list with blocking/warning rows, primary button "Vytvoriť objednávku v Money"); offer editor (lines with article match, DIN/ISO equivalent badge, quantity as requested with small info "bal. 200 ks" (never rounded), stock chip of all warehouses, price source chips
"naposledy 0,084 €", "e-shop −8 %"); compose screen like Roundcube (toolbar Uložiť · Priložiť · Podpis · Odpovede · ✦ AI;
fields Od with pencil, Komu with address-book and +, Predmet; rich-text toolbar; blue "Odoslať" button under the editor
and "Otvoriť v novom okne" at the right; right panel "Možnosti a prílohy" with a dashed drop zone "Maximálna povolená
veľkosť súboru je 75 MB", switches Potvrdenie o doručení / Oznámenie o stave doručenia / Zachovať formátovanie,
selects Priorita and Uložiť odoslanú správu do, and a second tab "✦ AI" with Napíš za mňa, Kratšie, Formálnejšie,
Preložiť do…, Doplniť z Money, Kontrola pred odoslaním); settings like Roundcube (three columns: sections "Nastavenia, Priečinky,
Identity, Odpovede, Môj profil, Filtre, Mimo kancelárie, AI asistent…", list of identities, form with labels left,
"Uložiť" button under the form) incl. an autonomy matrix (rows = AI actions, columns
"Vypnuté / Len navrhnúť / Pripraviť na schválenie / Urobiť a oznámiť"; sending e-mail is locked at "Pripraviť na
schválenie").
Login like Roundcube: white page, blue SMART logo, e-mail and password fields with icon boxes, full-width
button "PRIHLÁSIŤ", checkbox "Zostať prihlásený na tomto zariadení"; then a "Kto ste?" screen with 3 large person tiles (avatar initials, name, function:
Peter Hudák – vedúci pobočky, Jana Nováková – obchod, Marek Kováč – sklad) and "Pokračovať ako Jana"; the
person chip "Jana" sits at the bottom of the rail; compose shows "Odpovedá: Jana Nováková ▾" under Od and Jana's signature at the end (card layout: photo hexagon, NAME in capitals, function in blue, thin blue line,
phone, branch address, e-mail, web, SMART logo with "Spojovací materiál").
Mobile: list with swipe actions (left "Vybavené" green, right "Odložiť" amber), bottom nav (E-mail, Dnes, Doklady,
Kontakty, Viac), FAB "Vytvoriť", detail with the AI card on top and a sticky "Schváliť a odoslať" bar, assistant as a
bottom sheet.
Style: Inter, 14 px body, 4-pt spacing, radii 6/8/12, subtle shadows, brand blue #0F75BC (from the logo) for app
actions and links, violet #5B4CDB only for AI, WCAG AA contrast, light mode first, also show dark mode for the main
screen.
```

---------------------------------------------------------------------------------------------------
## 9. Definition of done for the design
- All components with variants/states; every frame of section 5 (SCREENS_SPEC §1/§13 + SETTINGS_SPEC W12-01…20)
  with its states; E1–E4; T1; M0–M18; flows 0–6 incl. 4b clickable.
- Variables imported from `design/tokens.json` (no hand-typed colours); app icon + favicon from the vector logo.
- Light + dark verified via variable modes; contrast checked (Stark/Able plugin).
- Copy matches UX_SPEC §7 and Roundcube SK labels; long-text stress cases included.
- Dev Mode ready: components linked, tokens = code tokens, redlines for list row, AI card, compose, mobile detail.
