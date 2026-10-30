# SCREENS_SPEC.md — every page and subpage of Smart Mail (v2.10)

Complete inventory of the application UI for Figma and for the coding agent. **Every screen ID below is drawn in the Figma file — frames and
states per ID in `docs/FIGMA_MAP.md` (DECISIONS D24).** The look to mirror is the customer's
Roundcube — anonymised screenshots in `design/reference/roundcube/` (DECISIONS D19). Visual tokens, component names and
microcopy come from `UX_SPEC.md`; settings pages are specified field by field in `SETTINGS_SPEC.md`; business rules
come from `PRODUCT_SPEC.md`, `ORDERS_SPEC.md`, `MONEY_API.md`, `AI_ASSISTANT.md`; screens and PDFs of Money documents
(received delivery note card, offer / order confirmation PDF) follow `DOCUMENTS_SPEC.md`. If a screen is not in this file, it
does not exist — do not invent pages. Every screen ID below is the Figma frame name prefix and the name of the React
route component (`ScreenW6f`, …) so design, code and tests use the same identifiers.

---------------------------------------------------------------------------------------------------
## 0. How each screen is described

| Field | Meaning |
|---|---|
| **Route** | URL in the web app (React Router). `:id` = UUID of Smart Mail objects, `:moneyId` = Money GUID |
| **Roles** | who can open it (person role, PRODUCT_SPEC §4); others get W16a "Nemáte prístup" |
| **Purpose** | one sentence — the job the user does here |
| **Entry** | how the user gets here |
| **Layout** | regions with widths (desktop 1440 × 900 reference) |
| **Content** | what is shown and where the data comes from |
| **Actions** | control → result (→ API) |
| **States** | loading / empty / error / offline / no permission / special |
| **Mobile** | the mobile counterpart (M-screen) and differences |
| **Done when** | testable acceptance (Playwright or manual) |

Global rules for all screens:
- Loading > 300 ms shows `Skeleton` in the shape of the content, never a full-page spinner.
- Every list remembers scroll position, filter and sort per user when navigating back.
- Destructive actions use `Dialog` with the object name in the title and a red primary button; reversible actions do
  not ask, they show `Toast` with "Späť" (10 s).
- Every action that writes to Money or sends e-mail outside the company goes through an AI card or a review screen
  with the approval button — no "quick" path around it.
- Deep links work for every route (refresh keeps the screen); unknown IDs → W16b "Nenašli sme".
- Money unavailable → `Banner` "Money S4 je nedostupné…" on screens that need Money; mail screens keep working.
- TEST agenda → amber pill "TEST" under the logo in the rail on every screen.

---------------------------------------------------------------------------------------------------
## 1. Sitemap and routes

| ID | Route | Title (SK) | Roles | Mobile |
|---|---|---|---|---|
| W1 | `/login` | Prihlásenie | everyone | M-W1 (own frame, see W1 Mobile) |
| W1a | `/login/2fa` | Overenie (2FA) | accounts with TOTP | same |
| W1b | `/who` | Kto ste? | branch logins | M0 |
| W1c | `/login?reason=password-changed\|expired` | Prihlásenie – heslo sa zmenilo / relácia vypršala | everyone | same |
| W2 | `/mail/:mailbox/:folder` | E-mail – zoznam + náhľad | viewer+ | M1 / M3 |
| W2c | `/mail/:mailbox/:folder/:threadId` | Vlákno (detail) | viewer+ | M3 |
| W2f | `/mail/:mailbox/view/:category` | AI triedenie – kategória | viewer+ | M1 (filtered) |
| W2g | `/mail/:mailbox/my/:view` (`assigned`, `waiting`, `snoozed`, `open`) | Moje | viewer+ | M1 |
| W2h | `/mail/all/:folder` | Všetky schránky | viewer+ with 2+ mailboxes | M1 |
| W2o | dialog (`?dialog=list-options`) | Nastavenia zoznamu | viewer+ | M1 (bottom sheet) |
| W2m | `/mail/:mailbox/:folder/:threadId/print` | Tlač | viewer+ | — |
| W2n | `/mail/:mailbox/:folder/:threadId/source/:messageId` | Zdroj správy | viewer+ | — |
| W3 | panel (no route; `?panel=assistant`) | Asistent | sales+ (viewer read-only answers) | M5 |
| W3b | panel (`?panel=customer`) | Zákazník | viewer+ | M10 |
| W4 | `/compose`, `/compose/:draftId` | Písanie správy | sales+ (viewer cannot send) | M4 |
| W5 | `/today` | Dnes | viewer+ | M6 |
| W5b | `/today/branch` | Prehľad pobočky | branch manager, admin | M6 (tab) |
| W6 | `/docs` → redirect to first allowed tab | Doklady | per tab | M13 |
| W6e | `/docs/delivery-notes` | Dodacie listy prijaté – zoznam | warehouse, accounting, admin | M13 |
| W6h | `/docs/delivery-notes/:id` | Dodací list prijatý – karta (ako v Money) | warehouse, accounting, admin | M13b |
| W6f | `/docs/orders/:id` | Kontrola objednávky | sales, accounting, admin | M12 |
| W6u | dialog (`?upload=1`) | Nahrať doklad | sales, accounting, warehouse, admin | M13 (button) |
| W7 | `/docs/offers` | Ponuky – zoznam | sales, admin | M13 |
| W7a | `/docs/offers/:id` | Ponuka – editor | sales, admin | M14 (read + approve) |
| W7b | `/docs/offers/:id/pdf` | Ponuka – náhľad PDF | sales, admin | same |
| W8 | `/docs/orders` | Objednávky – zoznam | sales, accounting, admin | M13 |
| W8d | `/docs/orders/:id/change` | Zmena objednávky | sales, admin | M12 (variant) |
| W8b | `/docs/reminders` | Upomienky | accounting, sales, admin | M13 |
| W8c | `/docs/complaints` + `/:id` | Reklamácie | sales, admin | M13 |
| W9 | `/contacts/:book` + `/:contactId` | Kontakty | viewer+ | M15 |
| W9a | `/contacts/company/:moneyId` | Zákazník 360 | viewer+ | M10 |
| W9b | `/contacts/company/:moneyId/orders` | Firma – Objednávky (šablóna, kódy) | sales, admin | — (desktop only) |
| W10 | `/search?q=` | Hľadanie | viewer+ | M8 |
| W11 | overlay (`Ctrl+K`) | Paleta príkazov | viewer+ | — (search on mobile) |
| W12 | `/settings/:section/:sub?` | Nastavenia (all sections → SETTINGS_SPEC) | user sections: all; admin sections: admin | M9 |
| W13 | overlay (first login) | Úvodná prehliadka | everyone | M-W13 (3 steps) |
| W14 | panel (bell) | Notifikácie | everyone | M16 |
| W15 | dialog (`?`) | Klávesové skratky | everyone | — |
| W15b | dialog (`?dialog=about`) | O systéme | everyone | M18 |
| W16a/b/c/d | `/403`, `/404`, `/500`, offline | Chybové stránky | everyone | same |
| W17 | `/maintenance` | Údržba | everyone | same |

Rail order (desktop) = bottom nav order (mobile): **E-mail, Dnes, Doklady, Kontakty**, then Nastavenia (desktop rail;
mobile under "Viac"). Doklady tabs are visible only if the person has a role for them; with no allowed tab the rail item
is hidden.

---------------------------------------------------------------------------------------------------
## 2. Global shell (present on every signed-in screen)

### G1 Rail (72 px, dark `bg/rail`) — like the customer's Roundcube
Top: white logo `design/brand/logo-smart-white.svg`, 52 px wide (click → W2 Doručená pošta); amber pill "TEST" under it
when the TEST agenda is connected. **Vytvoriť správu** (blue `SquarePen` icon + blue label, ellipsis — exactly like
Roundcube, not a filled button) → W4. Items: E-mail (badge = unread in current mailbox), Dnes (badge = suggestions to
approve), Doklady (badge = documents waiting for this person: dodacie listy na kontrolu + objednávky na kontrolu),
Kontakty, Nastavenia. Bottom: ✦ Asistent toggle (W3), Notifikácie (bell + count → W14), **PersonChip** (UX_SPEC
W2b), then Roundcube's items **Tmavý režim** (toggle), **O systéme** (W15b) and **Odhlásiť** (red icon). Height
< 820 px → Tmavý režim and O systéme move into the PersonChip menu. Active item: `bg/rail-active` + 3 px left bar
`primary-400`. Tooltips with shortcut.

### G2 Column headers (no global top bar — DECISIONS D19)
Like Roundcube, there is no bar across the whole window. Every column has its own 56 px header: on W2 the folder
column shows the mailbox name, the list shows the Roundcube list toolbar, the reading pane the message toolbar (UX_SPEC
W2). Other pages (Dnes, Doklady, Kontakty, Nastavenia, Hľadanie) have a page header in the first column: title or
breadcrumb (`Doklady › Objednávky › PO-45821`) and the page's own actions at the right (e.g. Settings: Vytvoriť,
Vymazať). Global search: the list search on W2 (last suggestion row "Hľadať všade – e-maily, firmy, doklady" → W10),
`/` and `Ctrl+K` everywhere. Money status: "Money ●" at the bottom of the folder column + banners (G6). Notifications
and the person: rail (G1).

### G3 Folder column (232 px; W2 only)
UX_SPEC W2. Header: mailbox name + `⋮` menu (Prepnúť schránku — mailboxes the account/person can access + "Všetky
schránky" when 2+; Akcie pre priečinky: Zhustiť, Vyprázdniť; Spravovať priečinky). Context menu on folder: Označiť
všetko ako prečítané, Vyprázdniť (Kôš, Nevyžiadaná pošta → confirm dialog), Nový podpriečinok, Premenovať, Vymazať
(confirm, not for special folders). Drop target for messages (move; Ctrl = copy). Bottom: quota (icon + bar + %, red
≥ 90 %) and "Money ●" status, like Roundcube's quota line.

### G4 Toasts
Bottom-left stack (max 3), auto-hide 5 s (10 s with "Späť"), pause on hover. Types: info, success (+ Späť), error (+
Skúsiť znova / Podrobnosti). Never use toasts for blocking errors — those are banners in the page.

### G5 Dialog patterns
Confirm (title = action + object, body = consequence, buttons Zrušiť / red primary), Form dialog (480–640 px), Drawer
(right, 480 px, for detail editing), BottomSheet on mobile. Esc closes; unsaved changes → "Zahodiť zmeny?" dialog.

### G6 Banners (top of content area)
Offline PWA (grey: "Ste offline – zobrazujeme uložené správy, odoslanie počká."), Money unavailable (amber), AI budget
exhausted (amber: "Denný rozpočet AI je vyčerpaný – triedenie beží len podľa pravidiel."), Password changed (red, with
"Prihlásiť znova"), Maintenance announced (info), Shadow mode for a feature (AI violet, admins only).

### G7 Drop zone
Dragging a file over any screen shows a full-screen overlay "Pustite súbor sem – doklad dodávateľa alebo
objednávka" → W6u.

---------------------------------------------------------------------------------------------------
## 3. Access

### W1 Prihlásenie — `/login`
- **Purpose**: sign in with the same e-mail + password as Roundcube.
- **Layout** (mirror of `design/reference/roundcube/06`): white page, no card; centred column 300 px: blue logo
  180 px (Figma, D24); field E-mail with leading `User` icon box; field Heslo with leading `Lock` icon box (show/hide eye); full-width
  primary button "PRIHLÁSIŤ"; checkbox "Zostať prihlásený na tomto zariadení" (default on for desktops recognised as
  shared branch PCs, off otherwise); link "Prihlásiť cez Microsoft / Google" (only if enabled); footer "Smart Mail" +
  version + Pomoc.
- **Actions**: Prihlásiť → `POST /api/auth/login` (IMAP auth) → W1a if TOTP, else W1b if the mailbox has 2+ persons,
  else last route or W2.
- **States**: submitting (button spinner, fields disabled); wrong credentials "Nesprávny e-mail alebo heslo." (no
  hint which one); mail server down "Mailový server je nedostupný – skúste o chvíľu."; rate-limited "Príliš veľa
  pokusov, skúste o 5 minút."; Caps Lock hint under password.
- **Mobile (M-W1, as drawn in Figma — D24)**: top-aligned column, full width with 24 px margins; blue logo 160 px
  and the subtitle "Prihláste sa e-mailom a heslom k pošte"; 36 px fields with an inline 16 px `User` / `Lock` icon
  (no icon box, no show/hide eye); checkbox "Zostať prihlásený na tomto zariadení" **above** the full-width 40 px
  button; errors as a red banner with a left border above the fields; no footer; keyboard type e-mail.
- **Done when**: login with a Roundcube account works; 5 wrong attempts lock for 5 min; password never logged.

### W1a Overenie (2FA) — `/login/2fa`
6 digit boxes (auto-advance, paste whole code), "Zapamätať zariadenie na 30 dní", link "Použiť záložný kód". Errors
inline; 5 failures → back to W1.

### W1b Kto ste? — `/who`
UX_SPEC W1b + PRODUCT_SPEC §2.0. Done when: 1 click selects (no PIN, DECISIONS D9); Enter continues as last person;
inactive person not shown; selecting is logged in audit.

### W1c Heslo sa zmenilo / relácia vypršala
W1 with an info banner on top ("Heslo k e-mailu sa zmenilo – prihláste sa novým heslom." / "Boli ste odhlásený po
12 hodinách nečinnosti."). After login → returns to the route where the user was; unsent drafts are kept (server).

---------------------------------------------------------------------------------------------------
## 4. E-mail

### W2 E-mail — `/mail/:mailbox/:folder`
- **Purpose**: read and process mail like in Roundcube, with AI help.
- **Layout** (mirror of `design/reference/roundcube/01` and `05`): G1 rail 72 · G3 folders 232 · list 360 (resizable
  300–520) · reading pane fluid (min 560) · optional assistant 380 (docked ≥ 1600 px, overlay below). No global top
  bar; each column has a 56 px header (G2).
- **Content**: UX_SPEC W2 (list rows `MessageRow`, quick filters, search scope); list data from local DB synced via
  IMAP; AI summary and category from `classifications`; assignee avatar, presence dot when somebody is replying.
- **Actions**: row click → W2c in the reading pane (URL updates); double click → W2c full width; checkbox / Shift /
  Ctrl → multi-select → W2e bulk bar; drag rows to G3 folder; keyboard (UX_SPEC §6); list header like Roundcube: **Výber** (Všetko, Aktuálna
  strana, Neprečítané, Označené príznakom, Invertovať, Nič; shows the checkbox column), **Konverzácie** (toggle),
  **Možnosti** (→ W2o), **Obnoviť** (IMAP refresh); search "Vyhľadať…" with scope menu; footer pagination « ‹ "Správy:
  1 – 50, z 30 163" [strana] › » in Zoznam mode (default, like Roundcube).
- **States**: W2a nothing selected (light grey logo watermark like Roundcube + "Vyberte správu" + mini summary "Dnes: 5 na schválenie, 2 urgentné");
  empty folder "Priečinok je prázdny"; empty inbox "Všetko vybavené ✓"; loading skeleton rows; IMAP error banner
  "Nepodarilo sa načítať priečinok – skúšame znova" with retry; Klasické zobrazenie (no AI section in folders, no
  summaries, AI cards collapsed).
- **Mobile**: M1 list, M2 drawer, M3 detail.
- **Done when**: Roundcube parity table (PRODUCT_SPEC §1) passes on this screen; 10 000 messages scroll smoothly.

### W2c Vlákno — reading pane / full view
- **Layout** (top → bottom): `Toolbar` (Roundcube order: Odpovedať, Odpovedať všetkým ▾, Poslať ďalej ▾, Vymazať,
  Nevyžiadané, Označiť, Viac | Prideliť, Vybavené, ✦); subject (`title`) + "Otvoriť v novom okne" + labels; header like
  Roundcube (avatar, Od with company chip from Money → opens W3b, Komu, Kópia, Dátum; links Zhrnutie · Hlavičky ·
  Čistý text; "Preložiť do slovenčiny" for foreign mail); `SecurityBanner` (phishing / IBAN change / DMARC / first-time sender); **AI cards**
  (`AiSuggestionCard`, max 2 visible + "Ďalšie návrhy (n)"); presence banner "Jana práve odpovedá" (if any); message
  body (sanitized, remote images blocked with bar "Zobraziť obrázky · Vždy od tohto odosielateľa"); attachments row
  (`AttachmentChip`: Náhľad → W2l lightbox, Stiahnuť, Uložiť do knižnice, Pripraviť dodací list prijatý /
  objednávku → W6u prefilled); older messages collapsed ("3 staršie správy"); internal notes timeline (yellow-grey
  cards with author + time) and composer "Interná poznámka… (@ pre zmienku)".
- **Actions**: Odpovedať / Všetkým / Poslať ďalej → W4 (inline reply in desktop-xl, else full W4); Vymazať (toast
  Späť); Nevyžiadané; Označiť menu; Viac menu (Archivovať, Tlač → W2m, Stiahnuť .eml, Upraviť ako novú, Zdroj → W2n,
  Presunúť do…, Kopírovať do…, Vystaviť prehlásenie o zhode… → dialog W2-PZ (#139), Vytvoriť filter z tejto správy → W12
  Filtre prefilled, Otvoriť v novom okne);
  **Prideliť** popover W2j; **Vybavené** (`E`, toast Späť; moves the thread to done); **Odložiť** W2i; AI card actions
  (UX_SPEC §3 states); translation toggle; company chip.
- **Dialog W2-PZ „Prehlásenie o zhode (atest 2.1)“** (#139, ADR-015; no Figma frame — existing Dialog + editable
  table): Odberateľ (prefilled from the sender), Doklad / zákazka, Miesto (default: the branch's town), Dátum vystavenia
  (today), Výrobky (Názov výrobku, Kód, Norma, Poznámka; Pridať riadok / remove). Buttons: Zrušiť · Náhľad PDF (no
  number, nothing stored) · **Vystaviť** (sales or admin of the branch or covering it; takes the next PZ-RRRR-NNNN,
  renders the PDF with the branch stamp and the manager's signature, attaches it to a reply draft in Koncepty and opens
  W4). Errors inline: no branch stamp, no manager signature, other branch, role. Disabled without an active person.
- **States**: message loading (body skeleton); large message "Zobraziť celú správu (2,3 MB)"; encrypted/S/MIME
  "Podpísaná správa ✓"; attachment infected (red chip, download disabled); thread changed by another person while open
  (info bar "Jana práve označila ako Vybavené").
- **Done when**: every toolbar action works with keyboard; notes never leave Smart Mail (not in IMAP).

### W2o Nastavenia zoznamu (dialog)
UX_SPEC W2o: Zoraďovanie, Systém zoraďovania, Režim zoznamu (Roundcube) + Hustota, Zobraziť AI zhrnutie; Uložiť /
Zrušiť. Saves to SETTINGS 01b (per person). Done when: the same three Roundcube fields with the same defaults (Dátum
prijatia, zostupne, Zoznam).

### W2e Hromadné akcie (multi-select bar)
Replaces the list header: "Vybraté: 12" · Označiť ako prečítané · Vybavené · Presunúť · Prideliť · Archivovať ·
Vymazať · Zrušiť výber. Max 500 items per action; progress toast for > 50.

### W2f AI triedenie – kategória
Same as W2 with list filtered by category; header shows category color + description ("Dopyty – žiadosti o ceny a
dostupnosť"); sorting by priority first. Empty: "Žiadne dopyty – AI ich sem zaradí automaticky."

### W2g Moje (Pridelené mne, Čakám na odpoveď, Odložené, Nevybavené)
List of threads across the person's mailboxes. Čakám na odpoveď: column "Čakám od" + "Pripomenúť" button (creates a
follow-up draft); Odložené: column "Vráti sa" with time; Nevybavené: needs_reply and not done, oldest first.

### W2h Všetky schránky
Unified list with a mailbox chip on each row; reading pane identical; compose defaults to the mailbox of the thread.

### W2i Odložiť (popover)
Options: Dnes poobede (15:00), Zajtra ráno (8:00), Pondelok ráno, Budúci týždeň, Vlastný dátum a čas (date-time
picker). Returns the thread to Doručená pošta with a "Vrátené z odloženia" chip.

### W2j Prideliť / Odovzdať (popover)
Search field; section "Pobočka Senica" (people with avatars, current assignee ✓); section "Odovzdať inej pobočke"
(branches); optional note; button Prideliť / Odovzdať. "Zrušiť pridelenie" when assigned.

### W2k Bezpečnostné varovanie (variant of W2c)
Red `SecurityBanner` "Pozor: zmenené bankové spojenie oproti posledným faktúram dodávateľa" / "Odosielateľ sa vydáva
za …" with "Prečo?" expandable; links in the body show real target on hover; attachments require "Rozumiem, otvoriť".

### W2l Náhľad prílohy (lightbox)
Full-screen dark overlay: PDF (pdf.js with pages, zoom), images (zoom, rotate), XML/ISDOC rendered as a table;
toolbar: Stiahnuť, Tlačiť, Importovať…, ←/→ between attachments, Esc closes.

### W2m Tlač · W2n Zdroj správy
Print: clean page with header (Od, Komu, Dátum, Predmet), body, attachments list; browser print dialog opens.
Source: monospace raw message with headers, "Stiahnuť .eml".

---------------------------------------------------------------------------------------------------
## 5. Písanie správy

### W4 Písanie — `/compose`, `/compose/:draftId`
- **Purpose**: write like in Roundcube; AI helps on request.
- **Layout** (mirror of `design/reference/roundcube/02`): content area replaces list + reading (full page). Header
  toolbar Uložiť · Priložiť · Podpis · Odpovede · ✦ AI; fields with a left label column (Od + pencil, "Odpovedá:
  [person] ▾", Komu + address book + "+", Predmet); editor toolbar in Roundcube order; editor (TipTap) with
  `SignatureBlock`; under the editor primary "Odoslať ▾" (left) and "Otvoriť v novom okne" (right); right panel 380
  "Možnosti a prílohy" with tabs Možnosti a prílohy (drop zone, Priložiť súbor, Potvrdenie o doručení, Oznámenie o
  stave doručenia, Zachovať formátovanie, Priorita, Uložiť odoslanú správu do) | ✦ AI (W4a).
- **Content/fields**: Od (identities allowed for the mailbox; default = mailbox of the thread), Komu / Kópia / Skrytá
  kópia / Odpovedať na (chips; autocomplete from contacts, Money persons and recent recipients; company tag on chip;
  external domain chip in amber when the thread was internal), Predmet; editor toolbar (B I U, zoznam, odkaz, obrázok,
  tabuľka, citácia, vymazať formát, HTML/Čistý text); attachments (drag & drop, paste image, "Z knižnice dokumentov",
  "Z Money: faktúra…").
- **Actions**: Odoslať (split: Odoslať / Naplánovať → W4c) → pre-send checks → W4b if warnings → send with undo
  toast (10 s); Uložiť (manual; autosave every 30 s to Koncepty, status "Uložené 10:42"); Priložiť (file picker; drop
  zone in the right panel); Podpis (menu: podpis osoby, bez podpisu, upraviť pre túto správu → W4e); Odpovede → W4d;
  Pravopis in the editor toolbar (SK/CZ/EN/DE); options in the right panel; Otvoriť v novom okne (W4f); leaving the
  page keeps the draft unless "Zahodiť koncept".
- **AI panel (W4a)**: "Napíš za mňa" (textarea + Napísať), chips Kratšie / Formálnejšie / Priateľskejšie / Opraviť
  gramatiku / Preložiť do… / Doplniť odpoveď na všetky otázky, "Doplniť z Money" (faktúra, neuhradené, stav
  objednávky, cena a dostupnosť artikla), "Kontrola pred odoslaním" live checklist (príloha spomenutá, príjemcovia
  z jednej firmy, nevyplnené [[DOPLNIŤ]], cudzí jazyk vs. jazyk zákazníka, faktúra patrí firme príjemcu). AI changes
  are shown as a diff with "Použiť" / "Zahodiť".
- **States**: sending (toolbar disabled), undo window (toast "Správa sa odosiela… Späť 10 s"), send failed (red banner
  with SMTP reason + Skúsiť znova; draft kept), offline (Odoslať → "Odošle sa po pripojení" queue), viewer role (send
  disabled with tooltip).
- **Mobile**: M4 full screen, ✦ opens M17 AI sheet.
- **Done when**: reply keeps References/In-Reply-To; draft appears in Roundcube Koncepty; signature of the active person.

### W4b Kontrola pred odoslaním (dialog)
List of warnings with icons (chýba príloha, externý príjemca, viac firiem v príjemcoch, [[DOPLNIŤ]] — blocking, cudzí
jazyk) and buttons "Upraviť" / "Odoslať aj tak" (disabled for blocking items).

### W4c Naplánovať odoslanie (dialog)
Presets: Zajtra 8:00, Pondelok 8:00, Vlastný čas; info "Správa sa odošle aj keď budete offline". Scheduled message
lives in Koncepty with a clock chip; can be canceled.

### W4d Odpovede (picker)
Searchable list of canned responses (personal + shared, with language tag); preview on hover; variables filled from
context ({meno}, {firma}, {cislo_faktury}…); missing variable → highlighted placeholder.

### W4e Upraviť podpis pre túto správu
Inline editor of the signature block for this message only; "Obnoviť podpis" link.

### W4f Okno písania (popup mode)
Same as W4 in a 720 × 640 floating window (setting), minimize to a bar at the bottom; max 3 open drafts.

---------------------------------------------------------------------------------------------------
## 6. Asistent

### W3 Asistent (panel 380) · W3b Zákazník (tab)
UX_SPEC W3. Additional details: header with context chip ("Kontext: ABC Stav s.r.o. · vlákno" — click to clear);
messages streamed; tool-call cards collapsed by default ("Hľadám v Money… ✓ 3 neuhradené faktúry", expand shows the
query in plain Slovak, never raw GraphQL); proposals as AiSuggestionCard; source chips (e-mail, doklad, firma) open the
object; input with `/` command list (W3c: /faktura, /neuhradene, /ponuka, /objednavka, /zhrnutie, /preloz,
/pripomen, /stav); history list (last 20 conversations) under a clock icon; "Nová konverzácia". Zákazník tab =
`CustomerCard` for the company of the selected thread; not matched → "Priradiť k firme" / "Založiť firmu v Money".
States: AI disabled for the person ("Asistent je vypnutý v Nastaveniach"), budget exhausted, Money offline (tools
greyed with reason). Mobile: M5 bottom sheet. Done when: 15 scripted tasks of Phase 5 succeed.

---------------------------------------------------------------------------------------------------
## 7. Dnes

### W5 Dnes — `/today`
UX_SPEC W5. Sections in this order: greeting + AI summary (max 5 sentences, "Aktualizované 6:30 · Obnoviť"); KPI
cards (click → filtered list); **Na schválenie** (compact AI cards with checkbox, "Schváliť všetky bezpečné (n)" opens a
confirmation list); **Urgentné**; **Doklady na kontrolu** (dodacie listy prijaté, objednávky — only for allowed roles);
**Neodpovedané > 24 h**; **Čakám na odpoveď** (with Pripomenúť); **Upomienky** (accounting). Empty day: "Nič
nečaká – pekný deň ✓". Mobile: M6.

### W5b Prehľad pobočky — `/today/branch`
For the branch manager: KPIs of the branch mailbox (nevybavené, najstaršie čakajúce, odpovede dnes), table by person
(pridelené, vybavené dnes, priemerný čas odpovede), list of unassigned threads older than 4 h with "Prideliť".
Read-only numbers; no ranking of people.

---------------------------------------------------------------------------------------------------
## 8. Doklady (documents hub)

Common layout of the hub: page title "Doklady", tabs (Dodacie listy · Objednávky · Ponuky · Reklamácie ·
Upomienky — only allowed ones; received invoices are not handled, DECISIONS D7; each with a count badge of items needing action), right "Nahrať doklad"
(W6u). List pages use `DataTable` (sticky header, column chooser, filter chips, search, saved filter per person,
pagination 50, row click → detail, checkbox → bulk actions).

### W6e Dodacie listy prijaté – zoznam
Columns (Money names): Číslo dokladu, Doklad prijatý, Dodávateľ, Vystavenie, Sklad. pohybu, Stredisko, Kód skladu,
Položky (spárované x/y), Celkom, Stav (Návrh / Chýbajú údaje / Pripravený / V Money / Chyba / Vrátený), Pobočka. Filters: Stav, Dodávateľ, Pobočka (default = active person's branch), Obdobie, Moje.
Row → W6h. Primary "Nahrať doklad" (W6u, type Dodací list). Empty: "Žiadne dodacie listy na kontrolu".

### W6h Dodací list prijatý – karta (ako v Money)
**Purpose:** check and create a received delivery note that looks exactly like the Money card "Dodací list prijatý –
Karta" (DOCUMENTS_SPEC §2 is binding: field order, labels, grid columns, number formats, rules DL-B1–B10/DL-W1–W8).
**Entry:** AI card on a supplier e-mail with an invoice or delivery note ("Príjem tovaru · 38 položiek → Pripraviť
dodací list"), W6e row, W6u upload. The supplier invoice is only the source of the lines (DECISIONS D7).
**Layout (1440):** page header (title, status, branch chip) 56 · action bar 44 (Vytvoriť v Money, Späť, Pridať do
adresára*; right: Originál dokladu, Kontrola (n); no Náklady — fees are not handled, D14) · tabs Všeobecné / Pripojené dokumenty / Texty / Poznámka ·
Všeobecné = header grid (left 2 columns of label/field pairs + groups Dátum / Podrobnosti; right sub-tabs Dodávateľ /
Kon. príjemca / Fakt. adresa + VAT recap) ~450 px (Money field layout, Figma W6h), then tabs Položky / Poplatky with Money item toolbar and the grid
(24 px rows, Money column order, sticky header, Σ row) filling the rest · right panel 420 (Originál PDF with field
highlight / Kontrola list), collapsible; when open the grid scrolls horizontally.
**Content:** draft from `documents` + `item_matching`; supplier card, codebooks and template document from the bridge;
branch values from SETTINGS 11e. Sklad. pohybu / Účt. prípadu show "pri zápise do Money" until created (D13); tab
Poplatky lists supplier fees read-only (D14); Vratka is always unchecked (D15).
**Actions:** line click → drawer "Riadok {n}" (supplier text, candidates, article search, unit conversion, warehouse,
"Zapamätať kód dodávateľa"); Opraviť hromadne; Pridať výberom; Zmazať; Nahor/Dolu; Excel; Σ; Legenda;
`Vytvoriť v Money` → confirm dialog with summary (dodávateľ, počet položiek, sklad, stredisko, celkom) → approval JWT →
bridge → W6h in state "V Money" with the Money number, read-back result and "Vrátiť" countdown (15 min, accounting).
**States:** loading (skeleton of the card), draft, needs_input (red counters on tabs and fields), creating (locked,
progress), created, failed (error text from Money + "Skúsiť znova" only after reconciliation), unknown (reconcile
banner), undone, Money offline (read-only), template missing (DL-B6 banner with link to SETTINGS 11e), duplicate
(DL-B3 banner with link to the existing Money document number).
**Mobile:** M13b — stacked groups in Money order, items as cards (Názov, Katalóg · Kód dodávateľa, Počet MJ, Jedn. cena,
status), "Vytvoriť v Money" in a sticky bar; editing a line in a bottom sheet.
**Done when:** DOCUMENTS_SPEC §10 acceptance; Playwright: open by deep link, fix 2 unmatched lines, create (mock),
read-back banner, undo.

### W6f Kontrola objednávky · W6g Objednávka vytvorená
UX_SPEC W6f + ORDERS_SPEC. W6g = W6f after create (read-only, success/diff banner, Vrátiť countdown, "Otvoriť návrh
potvrdenia"). The confirmation e-mail carries the PDF "Potvrdenie objednávky č. {Money číslo}" in the Money print
layout (DOCUMENTS_SPEC §5); W6g has "Náhľad potvrdenia (PDF)".

### W6u Nahrať doklad (dialog)
Drop zone + "Vybrať súbor" (PDF, JPG/PNG, XLSX, CSV, XML, ISDOC; max 25 MB), type select (Rozpoznať automaticky /
Doklad dodávateľa (faktúra alebo dodací list → Dodací list prijatý) / Objednávka zákazníka), optional
customer/supplier; after upload → spinner "AI číta doklad…" → opens the matching review screen (W6h / W6f).

### W7 Ponuky – zoznam · W7a editor · W7b PDF
List columns: Číslo (from Money after `CreateIssuedOffer`, e.g. PV263415 — DECISIONS D5; draft = "návrh"), Zákazník, Dátum vystavenia, Platnosť do, Celkom, Stav
(Koncept / Odoslaná / Prijatá → objednávka / Odmietnutá / Po platnosti), Vystavil, Pobočka; "Nová ponuka". W7a per
UX_SPEC W7: header fields named like the PDF (Dátum vystavenia, Dátum platnosti od/do), line grid with the PDF columns
(Označenie dodávky, Katalóg, Počet MJ, Cena za MJ, Sadzba, Základ, Celkom s DPH) + price source chips from Money
(`ProdejniCeny`) and stock chips (`WarehouseStocks`); W7b full-page preview of the PDF rendered from
`templates/print/document.html.j2` — **identical to the Money report "Ponuka vystavená"** (DOCUMENTS_SPEC §4; the
original Money PDF replaces it if the implementer adds an offer report endpoint) — with
"Odoslať e-mailom" and "Stiahnuť".
Status menu: Označiť ako prijatú (→ order flow W6f prefilled from the offer) / odmietnutú.

### W8 Objednávky – zoznam · W8d Zmena objednávky
UX_SPEC W8. Row → W6f/W6g; change rows → W8d diff screen.

### W8b Upomienky
Table of customers with overdue invoices (Zákazník, Po splatnosti suma, Počet faktúr, Najstaršia (dni), Posledná
upomienka, Kontakt). Select → "Pripraviť upomienky" → review list (one draft per customer, tone selector Zdvorilá /
Dôrazná, PDFs attached) → "Schváliť a odoslať vybrané". History tab "Odoslané upomienky".

### W8c Reklamácie
List (Zákazník, Faktúra/DL, Prijatá, Stav v Money, Pridelené). Detail: customer text + photos, referenced invoice lines
with checkbox, description fields (pre zákazníka / interná), primary "Vytvoriť reklamáciu v Money", then confirmation
reply draft with the complaint number.

---------------------------------------------------------------------------------------------------
## 9. Kontakty

### W9 Kontakty — `/contacts/:book`
Roundcube structure: left address books (Osobné adresy, Zdieľané, **Money – adresár** read-only, Naposledy použité)
and groups; middle list (search, letters index); right detail. Actions: Nový kontakt, Import (vCard/CSV), Export,
Pridať do skupiny, Vymazať (not for Money). Money contact detail shows "Upraviť v Money" (creates a suggestion, never
edits directly).

### W9a Zákazník 360 — `/contacts/company/:moneyId`
Header: name, IČO, DIČ, IČ DPH, address, discount, splatnosť, credit bar, VIP star. Tabs: **Prehľad** (KPIs: otvorené
faktúry, po splatnosti, obrat 12 mesiacov, posledná objednávka; AI summary of the relationship), **E-maily** (all
threads from visible mailboxes), **Doklady** (faktúry, objednávky, ponuky, reklamácie with status), **Kontakty**
(persons from Money + local), **Aktivity** (Money activities), **Objednávky** → W9b. Actions: Napísať, Poslať výpis
neuhradených, Pripraviť ponuku, Založiť objednávku z e-mailu.

### W9b Firma – Objednávky (šablóna a naučené kódy)
Form: column mapping for XLSX/CSV (table "Názov stĺpca u zákazníka → Pole"), predvolený sklad, doprava, akceptuje
ekvivalenty, potvrdenie (áno/nie, jazyk, príjemcovia, PDF). Table "Naučené kódy zákazníka" (Kód
zákazníka, Náš artikel, Prepočet, Potvrdil, Dátum, Použité ×) with search, edit, delete (confirm), Export CSV.

---------------------------------------------------------------------------------------------------
## 10. Hľadanie a paleta

### W10 Hľadanie — `/search?q=`
Query field with interpreted chips ("Od: Würth", "Obdobie: september 2026", "S prílohou") — chips removable/editable;
left filter column (Typ: E-maily, Prílohy, Firmy, Doklady v Money, Ponuky; Schránka; Priečinok; Obdobie; Kategória);
results grouped with "Zobraziť všetky (n)"; highlighting of matched words; Money documents show number, firm, amount,
status. Empty: "Nič sme nenašli" + tips. Mobile: M8.

### W11 Paleta príkazov (Ctrl+K)
UX_SPEC W11. Groups: Príkazy (Vytvoriť správu, Prejsť na Dnes, Nahrať doklad, Prepnúť osobu…), E-maily, Firmy,
Doklady, Nastavenia (every settings field is searchable — SETTINGS_SPEC §0.4); last row "Opýtať sa asistenta: …".

---------------------------------------------------------------------------------------------------
## 11. Nastavenia
W12 shell and every section/subsection: **SETTINGS_SPEC.md** (frames W12-01 … W12-20, mobile M9); look and section
order as the customer's Roundcube (`design/reference/roundcube/03`, UX_SPEC W12).

---------------------------------------------------------------------------------------------------
## 12. System screens

### W13 Úvodná prehliadka
5 popovers anchored to real UI (UX_SPEC W13) with "Ďalej" / "Preskočiť"; can be restarted from Pomoc. Branch logins
see a 6th step "Kliknite sem a prepnite osobu" (PersonChip).

### W14 Notifikácie (panel 380 from the bell)
Tabs Všetky / Nevybavené; items grouped Dnes / Včera / Staršie: icon by type (pridelené, zmienka, na schválenie,
dodací list na kontrolu, objednávka na kontrolu, zápis do Money zlyhal, synchronizácia zlyhala), text, time, unread dot; click →
object; "Označiť všetky ako prečítané"; link "Nastavenia notifikácií" (W12-08).

### W15 Klávesové skratky (dialog `?`)
Two columns grouped (Zoznam, Správa, Písanie, Navigácia, Doklady, Asistent); search field; link to settings.

### W15b O systéme (dialog from the rail)
UX_SPEC W15b: logo, version, Pomoc, Klávesové skratky, Zoznam zmien, Spustiť úvodnú prehliadku, link "Správa
schránky u poskytovateľa" (SETTINGS 12 URL, D20).

### W16 Chybové stránky
W16a 403 "Nemáte prístup k tejto stránke" + "Požiadajte správcu" + Späť; W16b 404 "Stránku sme nenašli"; W16c 500 "Niečo
sa pokazilo – chybu sme zaznamenali" + reference code; W16d Offline (PWA, cached shell) "Ste offline". All keep G1/G2
when signed in.

### W17 Údržba
Full page with expected end time; mail stays readable from cache if available.

### E1–E4 Odchádzajúce e-maily (HTML šablóny)
Not app screens, but designed like them (Figma page `Doklady` → section "E-maily"). Rules for all: HTML e-mail that
renders in Outlook, Gmail and Apple Mail — table layout, inline CSS, max width 640 px, fonts Arial/Helvetica
(no web fonts), text 14/21 px `#1B2430`, links `#0F75BC`, no images except the optional logo from the branch
signature; plain-text alternative is always generated; the signature is the branch template of the approving person
(SETTINGS 11c); never any AI wording ("vygenerované AI") in the e-mail.
| ID | E-mail | Content (source) | Visual |
|---|---|---|---|
| E1 | Potvrdenie objednávky | ORDERS_SPEC §10: thanks + our number + customer PO; table Váš kód · Artikel · Množstvo · Cena/MJ · Spolu; box "Zmeny oproti vašej objednávke"; doprava, adresa, splatnosť, spolu bez DPH / s DPH; PDF attached (optional) | table header `#EAF4FB`, row lines `#DFE3EA`, numbers right-aligned with tabular digits; changes box with 3 px amber left border `#E0A020` on `#FFF8E6` |
| E2 | Upomienka | SCREENS W8b: tone Zdvorilá / Dôrazná; table Faktúra · Splatnosť · Suma · Po splatnosti (dni); bank details from Money; invoice PDFs attached | same table style; total row bold; no red colours (polite tone) |
| E3 | Ranný prehľad e-mailom (to the employee) | AI_ASSISTANT §11: summary (max 5 sentences), counts (Na schválenie, Urgentné, Doklady na kontrolu, Čakám na odpoveď), up to 10 items with deep links into the app | internal look: logo, blue button "Otvoriť Smart Mail", counts as a 2 × 2 table |
| E4 | Otázka k objednávke | ORDERS_SPEC §10 clarification: list of unclear lines (customer text → what we need to know), reply instruction | numbered list, customer text in quotes, no table |

---------------------------------------------------------------------------------------------------
## 13. Mobile screens (390 × 844)

| ID | Screen | Desktop counterpart | Differences |
|---|---|---|---|
| M0 | Kto ste? | W1b | tiles 2 per row, remember on phone default on |
| M1 | Zoznam | W2/W2f/W2g/W2h | app bar, chips, swipe left Vybavené / right Odložiť, long-press multi-select, FAB |
| M2 | Priečinky (drawer) | G3 | mailboxes, folders, AI triedenie, Moje, quota |
| M3 | Detail vlákna | W2c | AI card first, sticky approve bar, bottom actions |
| M4 | Písanie | W4 | full screen, ✦ → M17 |
| M5 | Asistent | W3 | bottom sheet half/full |
| M6 | Dnes | W5/W5b | KPI chips scroll, batch approve, tab Pobočka for managers |
| M8 | Hľadanie | W10 | full-screen search with recent queries |
| M9 | Nastavenia | W12 | SETTINGS_SPEC §M9 (subset) |
| M10 | Zákazník | W3b/W9a | full-screen card, tabs Prehľad / Doklady / Kontakty |
| M11 | Notifikácie (system push) | W14 | push payloads + in-app list |
| M12 | Objednávka – kontrola | W6f/W8d | tabs Položky / Údaje / Originál, bottom sheet per line |
| M13 | Doklady | W6 hub | segmented tabs, lists as cards, "Nahrať" (camera for delivery notes) |
| M13b | Dodací list prijatý | W6h | Money groups stacked in Money order, item cards, sticky "Vytvoriť v Money" |
| M14 | Ponuka (čítanie + schválenie) | W7a | editing of lines only on desktop; approve/send allowed |
| M15 | Kontakty | W9 | list + detail, call/e-mail buttons |
| M16 | Notifikácie (panel) | W14 | full screen |
| M17 | AI pri písaní (sheet) | W4a | chips and "Napíš za mňa" |
| M18 | Viac | — | Kontakty, Nastavenia, Prepnúť osobu, Tmavý režim, O systéme, Odhlásiť |
Mobile-only rules: touch targets ≥ 44 px, safe areas, haptic on approve/swipe, pull-to-refresh on lists, camera upload
for delivery notes and orders (W6u), offline read of the last 7 days.

---------------------------------------------------------------------------------------------------
## 14. Coverage checklist (for Figma and for Playwright)
Every row of §1 has: a Figma frame per state listed under "States" (at least default, loading, empty, error), a mobile
frame per §13, and one Playwright test opening the route by deep link. CI fails when a route in `web/src/app/routes.ts`
has no ID from this file (route manifest test).
