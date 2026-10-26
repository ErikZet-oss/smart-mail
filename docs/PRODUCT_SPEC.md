# PRODUCT_SPEC.md — Smart Mail functional specification

Smart Mail is the company e-mail client of Smart s.r.o. (fastener e-shop, SK). It replaces **Roundcube** (IMAP/SMTP
webmail) and adds an AI assistant connected to **Money S4**. Users: 3–10 employees (sales, accounting, management)
plus **branches (pobočky)** where several people share one branch mailbox login, desktop + phone. UI language: Slovak only.

Product principles (use them to decide anything not specified):
1. **Familiar first** — anyone who used Roundcube can work on day one: same layout logic, same Slovak words, same
   folder names, same toolbar order. New things are additive.
2. **AI prepares, humans decide** — see AI_ASSISTANT.md §1 autonomy model.
3. **Everything about a customer in one place** — e-mail + Money context side by side.
4. **Fast** — keyboard, instant search, optimistic UI, < 100 ms list interactions, < 1.5 s first paint.
5. **Nothing extra** — if a feature is not in this spec, do not build it.

---------------------------------------------------------------------------------------------------
## 1. Roundcube parity (must have, same Slovak labels as Roundcube SK; reference = the customer's screenshots in
`design/reference/roundcube/`, DECISIONS D19)

| Roundcube | Smart Mail | Notes |
|---|---|---|
| Left menu: Vytvoriť správu, E-mail, Kontakty, Nastavenia; bottom Tmavý režim, O systéme, Odhlásiť | Left rail: **Vytvoriť správu**, **E-mail**, Dnes*, Doklady*, **Kontakty**, **Nastavenia**; bottom ✦ Asistent*, Notifikácie*, osoba*, **Tmavý režim**, **O systéme**, **Odhlásiť** | *new items added, nothing known moves |
| Folders: Doručená pošta, Koncepty, Odoslané, Nevyžiadaná pošta, Kôš + own folders (Archív, Dodávatelia, Faktúry, Kurier, Nitra, Senica, Trenčín …); mailbox name with ⋮ menu above | identical names, icons, counts & order (special-use folders from IMAP `SPECIAL-USE`, localized like Roundcube) | own folders keep IMAP names |
| Toolbar: Odpovedať, Odpovedať všetkým ▾, Poslať ďalej ▾, Vymazať, Nevyžiadané (tooltip "Označiť ako nevyžiadané"), Označiť, Viac | identical order, icon + label under icon; Archivovať in Viac | AI never replaces these |
| Označiť: Ako prečítané/neprečítané, Ako označené/neoznačené príznakom | identical | |
| Viac: Tlač, Stiahnuť (.eml), Upraviť ako novú správu, Zobraziť zdroj, Presunúť do…, Kopírovať do…, Otvoriť v novom okne | identical + Archivovať, "Vytvoriť filter z tejto správy" | |
| Message header: Od, Komu, Dátum; Zhrnutie · Hlavičky · Čistý text; attachment with size and ▾ | identical + company chip from Money, Preložiť | |
| Search box above list with scope (Aktuálny priečinok / Tento a podpriečinky / Všetky priečinky) and fields (Predmet, Od, Komu, Kópia, Telo) | identical + AI natural-language search ("faktúry od Würth za september") | |
| List header Výber · Konverzácie · Možnosti · Obnoviť; Nastavenia zoznamu (Zoraďovanie, Systém zoraďovania, Režim zoznamu); two-line rows; pagination "Správy: 1 – 50, z …" | identical (+ Hustota, AI zhrnutie in the dialog) | default Zoznam, Dátum prijatia, zostupne, 50 per page |
| Compose: toolbar Uložiť, Priložiť, Podpis, Odpovede; Od (identity + pencil), Komu (+ adresár, +), Kópia, Skrytá kópia, Odpovedať na, Preposlať na, Predmet; editor; Odoslať under the editor, Otvoriť v novom okne; panel Možnosti a prílohy (Priložiť súbor, Potvrdenie o doručení, Oznámenie o stave doručenia, Zachovať formátovanie, Priorita, Uložiť odoslanú správu do) | identical + ✦ AI tab in the right panel + "Odpovedá: osoba" | drag & drop attachments, paste images |
| Settings: Nastavenia, Priečinky, Identity, Odpovede, Informácie o používateľovi, Filtre, Mimo kancelárie, Nastavenia e-mail schránky | identical names & order (Informácie o používateľovi → Môj profil) + new sections; Nastavenia e-mail schránky = provider info + button to the provider's administration (D20) | Filtre/Mimo kancelárie via ManageSieve (same server scripts as Roundcube) |
| Kontakty: adresáre, skupiny, import/export vCard | identical + Money adresár as read-only source | import Roundcube vCard export |
| Quota: icon + bar + % at the bottom of the folder column | identical (red ≥ 90 %) | IMAP QUOTA |
| Login: logo, user + password with icons, button PRIHLÁSIŤ | identical + "Zostať prihlásený" | same IMAP credentials |
| Keyboard: arrows, Enter, Delete, Shift+Delete | identical + new shortcuts (UX_SPEC §6) | |

Transition support: optional **"Klasické zobrazenie"** per user (hides AI category list, summaries and the assistant
button; AI cards still appear but collapsed) for the first weeks; onboarding tour "Čo je nové oproti Roundcube" (5
steps); printable cheat sheet (1 page).

---------------------------------------------------------------------------------------------------
## 2. Modules

### 2.0 Pobočky a osoby — "Kto odpovedá?" (shared branch mailboxes, one click to switch person)
Situation today: every branch has ONE mailbox (e.g. `senica@smartsro.sk`); all people of the branch log into
Roundcube with that mailbox's e-mail + password; the branch manager usually replies, otherwise anybody; people switch
the signature manually. Goal: **keep the same login, but one click on your name sets the signature automatically.**
Design rule: the simplest possible operation — no new passwords, no extra step when sending.

**Login**
- Login form = e-mail + password exactly like Roundcube. The backend authenticates against the mail server (IMAP
  LOGIN/AUTHENTICATE with the given credentials over TLS) — the mail server stays the only place where passwords are
  managed. Background sync and AI need the mailbox credential also when nobody is logged in: it is stored encrypted
  per mailbox (Settings › Schránky, Fernet). A successful login with a different password for that mailbox replaces
  the stored credential automatically (so a password change on the mail server needs no admin work); a failing
  background login raises an admin notification and a banner "Heslo k e-mailu sa zmenilo – prihláste sa znova".
- Personal accounts (e.g. Erik, accounting) log in the same way with their personal mailbox; optional Microsoft/Google
  login (OIDC) and TOTP remain available for admins.
- "Zostať prihlásený na tomto zariadení" (default on for branch PCs): session 30 days, re-login after password change on
  the mail server (IMAP auth fails → logout with message "Heslo k e-mailu sa zmenilo, prihláste sa znova").

**Person picker ("Kto ste?")** — shown right after login to a mailbox that has more than one person profile:
- Full-screen card: branch name + mailbox, big tiles with avatar (photo or initials), name and function, ordered:
  manager first, then alphabetically; last used person on this device is highlighted with "Pokračovať ako Jana".
- **One click selects** the person. No PIN (DECISIONS D9).
- The device remembers the last person (per browser, localStorage + server-side device id); next login shows the picker
  with that person pre-selected, Enter continues.
- Mailbox with exactly one person → no picker (person is selected automatically).
- Admin/central users who see several branch mailboxes choose the person once for themselves (their own profile).

**Active person everywhere**
- Top-right **PersonChip** "J Jana ▾" (avatar + first name). Click → popover with the branch people → **one click
  switches** (no logout, no reload; drafts stay). Keyboard: `Ctrl+Shift+P`.
- Optional "Opýtať sa po nečinnosti" (admin, per branch; default **off**; values 30/60/120 min): after inactivity the
  picker reappears with the current person pre-selected (Enter = same person).
- Mobile: picker after login; phones are usually personal → "Zapamätať na tomto telefóne" default on.

**Signature (the main reason)**
- Each branch has a **signature template** (HTML, per language SK/CZ/EN/DE) with variables
  `{meno}`, `{priezvisko}`, `{funkcia}`, `{telefon}`, `{mobil}`, `{email_osobny}` (optional), `{pobocka}`,
  `{adresa_pobocky}`, `{telefon_pobocky}`, `{oteviracie_hodiny}`, plus logo. Each person has their values.
- Compose shows under "Od" a read-only line **"Odpovedá: Jana Nováková ▾"** — the signature in the editor is already
  Jana's. Changing the person in this dropdown swaps the signature block in place (signature is a separate,
  non-editable block in TipTap with "Upraviť podpis len pre túto správu"). The From address stays the branch address.
- Reply/forward/new message, AI drafts and canned responses (Odpovede) all use the active person's signature and the
  e-mail language (signature language = draft language).
- If the user changes the active person while a draft is open, the draft keeps its signature and shows a hint
  "Podpis: Peter – zmeniť na Janu?" (one click). Never change a signature silently in an existing draft.
- Roundcube identities are not changed (parallel run keeps working).

**What the active person drives** (all stored as `person_id` + `account_id`):
- "Jana práve odpovedá" presence and draft lock, assignment ("Prideliť: Jana"), "Pridelené mne", internal notes
  (`@Jana`), audit log ("odoslala Jana Nováková z senica@"), approvals of Money writes, AI style profile per person
  (opt-in), notifications (push to the person's phone if they enabled it), Dnes greeting ("Dobré ráno, Jana").
- Permissions are per **person profile** (role: viewer/sales/warehouse/accounting/admin) within the mailboxes the
  account can access; Money write approvals require a role that allows it (PRODUCT_SPEC §4).
- Persons (name, function, phone, photo, role) and branch signature templates are added, edited and deleted by the
  customer in Settings › Pobočky a osoby (DECISIONS D10).

**Handing over between branches**
- Toolbar "Prideliť" lists people of this branch and, below, other branches: "Odovzdať pobočke Trenčín" + note.
  Implementation: IMAP APPEND copy of the message to the target branch mailbox INBOX (both mailboxes are connected by the
  admin), flag `$SmartHandedOver` + internal note in both threads with links; the original thread becomes "Vybavené –
  odovzdané pobočke Trenčín". The customer is not contacted automatically; AI may prepare a short reply "Vašu požiadavku
  odovzdali sme kolegom z pobočky Trenčín" (approval).

**Branch in Money (cenník, stredisko, sklad)** — every branch has its own price list (`PriceLists`), centre
(`Centres` = číslo pobočky / stredisko) and warehouse in Money (warehouses today: 10 Trnava, 20 Senica, 30 Nitra,
40 Trenčín — DECISIONS D4; all values are dropdowns loaded from Money). They are set once per branch in Settings › Pobočky a
osoby › Money (SETTINGS_SPEC 11e) and drive every Money document created from that branch:
- **Which branch a document belongs to**: the branch of the mailbox where the e-mail arrived; manual upload → branch
  of the active person; person covering several branches or a central mailbox (info@, faktury@) → branch select on the
  review screen (default = "Centrála" profile from Settings 13c). The chosen branch is shown on every review screen as
  a chip "Pobočka Senica · Stredisko 20 · Cenník 20-bez DPH · Sklad 20" (UX_SPEC BranchChip, D23) and can be changed there (warning W-BR1 when it
  differs from the mailbox branch).
- **Received delivery note**: header `Stredisko_ID` = branch centre, every item
  `Stredisko_ID` = branch centre and `ObsahPolozky { Sklad_ID = branch warehouse, Cenik_ID = branch price list }`,
  numerical series = branch override if set (else company default). Goods are received to the right warehouse.
- **Customer orders and offers**: prices from `ProdejniCeny(FirmaID, SkladID = branch warehouse)` and the branch price
  list (`Cenik_ID`), order header + items `Stredisko_ID` = branch centre, items `Sklad_ID` = branch warehouse (no stock
  handling, D6).
- Missing branch Money settings → blocking rule "Pobočka nemá nastavený cenník / stredisko / sklad" on any Money write
  from that branch (ORDERS_SPEC B15, DOCUMENTS_SPEC DL-B1).

**Branch overview for the manager** (Dnes › Pobočka): unanswered e-mails older than X hours, by assignee, waiting for
customer, AI suggestions waiting for approval; only for the manager and admin roles.

Edge cases (tests required): person deactivated while selected → next request returns 409 and the picker opens;
two people on two PCs with the same person selected → allowed (presence shows the same name twice "Jana (2 zariadenia)");
a person in two branches (e.g. covering) → appears in both pickers with branch-specific signature values;
no person selected → read-only mode until a person is chosen (cannot send/approve).

### 2.1 E-mail (main screen)
- **Mailboxes**: a user can have several (personal erik@, shared info@, faktury@, objednavky@). Switcher at the top
  of the folder column + "Všetky schránky" unified view. Shared mailbox permissions per user (read / send as).
- **Folders**: IMAP folders with unread counts, drag & drop messages to folders, create/rename/delete (Settings ›
  Priečinky), subscribe.
- **AI views** (virtual, across folders of the selected mailbox): Dopyty, Objednávky, Žiadosti o faktúru, Doklady
  dodávateľov, Platby, Reklamácie, Doprava, Žiadosti o dokument, Dodávatelia, Feed (newsletters + notifications).
  Spam stays in the IMAP Nevyžiadaná pošta folder.
- **Moje**: Pridelené mne, Čakám na odpoveď (follow-ups), Odložené (snooze), Nevybavené (needs_reply and not done).
- **Message list**: sender (company name if matched + person), subject, 1-line AI summary (toggle), date, icons
  (attachment, flag, replied/forwarded, AI suggestion ready ✦, assigned avatar, priority dot), category chip.
  Density: Kompaktná (Roundcube-like, 1 row + subject) / Pohodlná (with summary). Infinite scroll.
  Multi-select with checkboxes (hover) and Shift/Ctrl click. Quick filters: Všetko, Neprečítané, Označené, S prílohou,
  Nevybavené.
- **Thread states**: Otvorené / Čaká na zákazníka / Vybavené (button "Vybavené" `E`), Odložené do … (`S`: dnes poobede,
  zajtra ráno, pondelok, vlastný čas). Done = IMAP `\Seen` + custom keyword `$SmartDone`; snooze stored in DB.
- **Assignment**: "Prideliť" to a person of the branch/mailbox (+ optional note) or "Odovzdať pobočke…" (§2.0);
  assignee gets notification; avatar on the row.
- **Collision detection** in shared mailboxes: "Jana práve píše odpoveď" banner (presence via WebSocket); draft lock.
- **Internal notes** on a thread (`@meno` mentions), visible only inside Smart Mail, never sent.
- **Reading pane**: header (Od, Komu, Kópia, Dátum, Predmet), security banner (phishing/IBAN change/DMARC fail),
  AI suggestion card(s), body (sanitized HTML, remote images blocked → "Zobraziť obrázky" / "Vždy zobraziť od …"),
  attachments (preview PDF/images inline, download, "Uložiť do Knižnice", "Pripraviť dodací list prijatý" / "Pripraviť objednávku"),
  translation toggle ("Preložiť do slovenčiny") for foreign mails, thread with collapsed older messages.
- **Toolbar** as Roundcube + right side: ✦ Asistent (toggle panel), Zákazník (toggle panel tab).

### 2.2 Písanie správy (compose)
- Full content area (Roundcube style) or popup window (setting). Fields as in Roundcube; recipient autocomplete from
  local contacts + Money persons + history (shows company name).
- Rich text editor (TipTap): bold, italic, underline, lists, link, quote, table (simple), image paste, clear format;
  "Čistý text" toggle.
- Identities with signatures (HTML; editor with source-code view and images like Roundcube, D22), signature per
  language (SK/EN/DE) auto-chosen by reply language. Uploaded signature images go as inline CID parts.
- **Odpovede** (canned responses, like Roundcube) with variables `{meno}`, `{firma}`, `{cislo_faktury}`, `{suma}`,
  `{datum_splatnosti}`, `{moje_meno}`; personal and shared.
- Attachments: upload, drag & drop, from Money (invoice/proforma PDF picker for the recipient's company only), from
  Knižnica dokumentov, from previous e-mails in the thread.
- **AI panel in compose**: "Napíš za mňa" (prompt → draft), rewrite actions (AI_ASSISTANT §6), "Preložiť do…" with
  side-by-side Slovak view, "Doplniť z Money" (faktúra, neuhradené faktúry, stav objednávky), "Skontrolovať pred
  odoslaním" (attachments, unanswered questions, tone, recipient/doc check).
- Autosave draft every 30 s to IMAP Koncepty.
- **Odoslať** with undo window (default 10 s, setting 0–30 s) → toast "Správa odoslaná · Späť".
  **Naplánovať odoslanie** (date/time). After send: optional "Zapísať do Money ako aktivitu" (default on when linked).
- Pre-send checks (UX: inline warnings, not modal unless blocking): missing attachment, `[[DOPLNIŤ]]` placeholder,
  external recipients in reply-all, new recipient, document/recipient mismatch (blocking), large attachments (> 20 MB
  → suggest link).

### 2.3 Asistent (side panel / mobile bottom sheet)
See AI_ASSISTANT.md §3. Tabs: **Asistent** (chat) and **Zákazník** (customer card). Opens with `Ctrl+J`.

### 2.4 Dnes (morning briefing + work queue)
- Greeting + AI summary (max 5 sentences).
- Cards with counts that open filtered lists: Urgentné, Na schválenie (AI návrhy), Dodacie listy na kontrolu,
  Neodpovedané > 24 h, Čakám na odpoveď > 3 dni, Upomienky na odoslanie, Odložené na dnes.
- "Na schválenie" list with batch approval ("Schváliť všetky bezpečné").
- Personal stats (small, optional): vybavené dnes, priemerný čas odpovede.

### 2.5 Doklady
Tabs:
- **Faktúry prijaté are not handled** (DECISIONS D7): Smart Mail never imports received invoices into Money. A supplier
  invoice that arrives with goods is only the source of the lines for the received delivery note below.
- **Dodacie listy prijaté** — supplier delivery notes or supplier invoices (e-mail/PDF/photo from the warehouse) are
  loaded into a **Dodací list prijatý that looks exactly like the Money card** (W6h, DOCUMENTS_SPEC §2: same labels,
  field order, item columns, number formats; branch stredisko, sklad and číselný rad filled automatically; lines matched
  via our Katalóg ↔ supplier code from the Money catalog; status chip per line: Kód dodávateľa / Naučené / EAN /
  Náš kód / Z objednávky / Návrh AI / Nespárované; unit conversion "25 bal × 200 = 5 000 ks"; price vs last purchase
  price) → `CreateReceivedDeliveryNote`. This is the only purchasing write (D7).
- **Ponuky** — list with statuses, offer editor (customer, validity, lines with article match, DIN/ISO equivalents,
  quantities exactly as requested (no packaging rounding, package size shown as information — DECISIONS D17),
  **customer price from Money** after discount, **stock from Money** of all warehouses as information (D18),
  alternatives when out of stock, notes, delivery/payment terms), PDF preview, "Odoslať e-mailom", "Prijatá →
  Vytvoriť objednávku v Money". **Offers are created in Money (`CreateIssuedOffer`) and numbered by Money** (DECISIONS
  D5; Smart s.r.o. arranges `IssuedOffer` in the API). The offer PDF is the Money report if the API gets an offer report,
  otherwise the copy of the Money print report "Ponuka vystavená" (DOCUMENTS_SPEC §4) with the Money number.
- **Faktúry vystavené** are never created in Smart Mail: the original PDF is downloaded from Money (REST report) and
  attached to the e-mail (DOCUMENTS_SPEC §6).
- **Objednávky** (full spec: `docs/ORDERS_SPEC.md`) — customer orders from e-mail body, PDF, scan, XLSX/CSV, UBL XML
  or a reply accepting our offer. List filters: Na kontrolu (needs_input/ready) / Vytvorené / Potvrdené / Vybavené /
  Zamietnuté / Zmeny a storná; columns Zákazník, Číslo obj. zákazníka, Prijaté, Položky (zelené/žlté/červené),
  Suma (naša), Stav v Money, Pridelené. **Review screen "Kontrola objednávky"** (UX_SPEC W6f): original document left
  with highlighted lines; right: header (customer card with credit/overdue/discount, PO number, delivery address,
  transport, payment, requested date, notes), lines (customer code/text → our article with method chip, quantity
  customer → ours (no packaging rounding, no stock handling — D6), unit price ours vs customer), checks (B-rules block, W-rules need a click),
  totals. Buttons: "Vytvoriť objednávku v Money" (primary), "Opýtať sa zákazníka" (clarification e-mail), "Uložiť",
  "Zamietnuť". After create: Money number + read-back result, "Vrátiť" for 15 min, confirmation e-mail draft
  (Potvrdenie objednávky with all changes vs. request). Changes/cancellations show a diff card and prepare a task +
  reply (Smart Mail never edits Money orders). Status chip in the thread (Prijatá / Čiastočne vybavená / Vybavená /
  Stornovaná) and optional "Tovar odoslaný" reply. Learned customer codes are kept per customer.
- **Reklamácie** — complaints detected in e-mail → prepared "Reklamácia prijatá" in Money with items from the
  referenced invoice → confirmation reply with the complaint number; status from Money.
- **Upomienky** — customers with overdue invoices (from Money), select → prepared reminder e-mails.

### 2.6 Kontakty (Roundcube-like + customer 360)
- Left: address books (Osobné adresy, Zdieľané, **Money – adresár** read-only), groups. Middle: list with search.
  Right: detail. For Money companies: **Zákazník 360** — Money data, contact persons, open/overdue invoices, recent
  orders, activities, recent e-mails (from all mailboxes the user can see), notes; actions: Napísať, Poslať výpis
  neuhradených faktúr, Pripraviť ponuku, Upraviť kontakt v Money (proposal). Tab **Objednávky** of a company: order
  template (column mapping, warehouse, transport, equivalents, confirmation settings) and learned
  customer codes (table, edit, CSV export) — ORDERS_SPEC §16.
- Import vCard/CSV (Roundcube export), export vCard.

### 2.7 Hľadanie
One input everywhere (`/` or `Ctrl+K`). Results grouped: E-maily, Prílohy, Kontakty/Firmy, Doklady v Money (invoice
numbers, orders), Ponuky. Filters as chips (Od, Komu, Priečinok, Kategória, S prílohou, Obdobie). Natural-language
queries are translated by AI into filters (shown as editable chips).

### 2.8 Knižnica dokumentov
Shared library: VOP, reklamačný poriadok, katalógy, cenníky PDF, technické listy, atesty/certifikáty (3.1, zhody, RoHS,
REACH), registračné údaje firmy, bankové spojenie letter. Metadata: type, product/norm tags, validity date (expiring
certificates highlighted). AI can attach from here; users can attach via compose. Upload from e-mail attachment.

---------------------------------------------------------------------------------------------------
## 3. Settings (Nastavenia) — complete tree
**Field-level specification (controls, defaults, validation, help texts, scopes, save behaviour): `SETTINGS_SPEC.md`
— authoritative, numbered 01–20** (01–09 user; 10 Používatelia a role, 11 Pobočky a osoby, 12 Schránky, 13 Money S4,
14 Nákup a sklad, 15 Objednávky, 16 Katalóg a ceny, 17 AI – správa, 18 Knižnica, 19 Audit log, 20 Systém). The tree
below is the functional summary.

User sections (every user):
1. **Nastavenia** (Roundcube's preferences)
   - Všeobecné: jazyk (SK), časové pásmo, formát dátumu, téma (Svetlá / Tmavá / Podľa systému), Klasické zobrazenie.
   - Zobrazenie schránky: rozloženie (Tri stĺpce / Zoznam bez náhľadu), hustota (Kompaktná / Pohodlná), zobraziť AI
     zhrnutie v zozname, konverzácie zapnuté, počet správ na stránku, označiť ako prečítané (ihneď / po 3 s / nikdy),
     po vymazaní/archivovaní otvoriť (ďalšiu / predchádzajúcu / zoznam).
   - Zobrazenie správ: obrázky z internetu (Nikdy / Od známych odosielateľov / Vždy), preferovať HTML, predvolená
     znaková sada, zobraziť prílohy pod správou.
   - Písanie správ: HTML/čistý text, písmo a veľkosť, citovanie (nad/pod citáciou), automatické ukladanie konceptu,
     odoslanie s oneskorením (0–30 s), potvrdenie o doručení predvolene, pridávať podpis pri odpovedi, okno písania
     (celá plocha / vyskakovacie okno).
   - Klávesové skratky: zapnuté, zoznam.
2. **Priečinky** — like Roundcube: search, list with subscription switches, Vytvoriť / Vymazať / Vyprázdniť, quota;
   rename, special-use mapping, "Súkromné – AI nespracúva" flag. Own folders filled by Sieve filters (Nitra, Senica,
   Trenčín, Dodávatelia, Faktúry, Kurier …) are processed by AI like Doručená pošta (D21).
   **Nastavenia e-mail schránky** (after Mimo kancelárie, like Roundcube) — provider info + link out (D20).
3. **Identity** — name, e-mail (allowed per mailbox), organization, reply-to, bcc, HTML signature per language
   (WYSIWYG + `<>` Zdrojový kód + images, D22), default.
   **Môj profil** (active person): meno, funkcia, telefón, mobil, foto, osobný štýl AI;
   preview of the branch signature with my values.
4. **Odpovede** — canned responses (personal / shared), variables help.
5. **Filtre** — Sieve rules (ManageSieve), same as Roundcube; editor with conditions/actions; plus "AI pravidlá" link.
6. **Mimo kancelárie** — Sieve vacation (subject, body, dates, addresses) + AI option "počas neprítomnosti prideľ
   nové e-maily kolegovi".
7. **AI asistent** — on/off, autonomy levels per action set by each login itself (D8; hard rule: external send and
   Money writes always need approval), personal style profile (generate /
   edit), languages, show summaries, briefing time + e-mail digest, follow-up days, assistant memory (clear).
8. **Notifikácie** — push (PWA) on/off per category (Urgentné, Pridelené mne, Na schválenie, Zmienky), quiet hours,
   sound, e-mail digest.
9. **Bezpečnosť** — password/2FA (if local login), active sessions (sign out others), connected devices (PWA).

Admin sections:
10. **Používatelia a role** — invite, roles (admin, sales, warehouse, accounting, viewer), Money user mapping
    (Staff/User GUID).
10b. **Pobočky a osoby** — branches (name, mailbox, address, phone, opening hours, logo), people per branch (name,
    function, phone, mobile, photo, role, Money obchodník, active), manager flag, signature template per language (HTML editor with source code and images, D22) with
    live preview, branch folders (D21), add / edit / delete persons, "Opýtať sa po nečinnosti" (off/30/60/120 min),
    "Zostať prihlásený" days, branch overview recipients.
11. **Schránky** — add IMAP/SMTP/Sieve accounts (host, ports, TLS, auth), shared mailbox access matrix, special folders.
12. **Money S4** — bridge status (TEST/PROD label, API version, latency, last sync), probe report upload, report IDs
    per document type and language; **codebook selects loaded from Money** (číselné rady, predkontácie, členenie DPH,
    sklady, strediská, zákazky, činnosti, spôsoby platby/dopravy) as defaults per document type and per supplier;
    template = last document of the partner (on/off); **nákup:** only received delivery notes (D7), warehouse = branch
    warehouse, price deviation warning %,
    **Kódy dodávateľov** (learned mappings table: search, edit, delete, CSV export); activity types; undo window; sync now.
13. **Objednávky** — číselná rada, zákazka/činnosť (stredisko and warehouse = branch), mapping user → obchodník,
    customer price tolerance, credit check (off/warn/block), overdue threshold, norm equivalents accepted, transport text mapping, shipping as an item (article + threshold),
    print customer instructions, confirmation templates SK/CZ/EN/DE + PDF on/off + auto-draft, ignored senders (e-shop),
    reminder hours for unresolved orders, price mode (admin, from probe). No stock, reservation or rounding (D6).
    Full list: ORDERS_SPEC §16.
14. **Katalóg a ceny** — default warehouse for prices/stock, price source priority (Money customer price →
    last sold price → manual), offer numbering = Money (D5), offer PDF = Money report layout (company header, logo, text
    under the table, footer system line, VOP link), default validity,
    payment/delivery terms, DIN/ISO equivalents table (editable).
15. **AI – správa** — provider/region, models, daily budget, overview of autonomy per login (no maximum, D8), categories on/off, VIP
    customers, company style guide, knowledge base cards, rules (natural language → structured), shadow mode, usage
    & cost, accuracy metrics (approved without edit %, by category).
16. **Knižnica dokumentov** — types, retention, expiring certificates reminder.
17. **Audit log** — filter by user/action/date, export CSV.
18. **Systém** — backups status, storage, sync health, version, maintenance (re-index, re-process last N days).

---------------------------------------------------------------------------------------------------
## 4. Roles & permissions

| Capability | viewer | sales | warehouse | accounting | admin |
|---|---|---|---|---|---|
| Read assigned mailboxes | ✓ | ✓ | ✓ | ✓ | ✓ |
| Send / approve replies, invoice sends, reminders, offers | | ✓ | | ✓ | ✓ |
| Create orders, complaints, companies in Money (approve) | | ✓ | | ✓ | ✓ |
| Confirm item matching, create received delivery notes | | | ✓ | ✓ | ✓ |
| Undo own received delivery note / order (15 min) | | ✓ | ✓ | ✓ | ✓ |
| Override recipient/document mismatch (with reason) | | | | | ✓ |
| Admin settings, users, mailboxes, Money, AI | | | | | ✓ |
Enforced in the API (dependencies), UI only hides.

---------------------------------------------------------------------------------------------------
## 5. Notifications
PWA Web Push + in-app toasts + bell menu: Urgentné nové, Pridelené mne, Zmienka v poznámke, Návrhy na schválenie
(batched max 1× per 30 min), Dodací list na kontrolu (warehouse, accounting), Nová objednávka na kontrolu (sales; urgent if
the requested date is within 3 days), Objednávka nevyriešená X hodín (sales), Import zlyhal, Synchronizácia zlyhala (admin).
Quiet hours respected except "Urgentné" if the user allows it.

---------------------------------------------------------------------------------------------------
## 6. Migration from Roundcube
1. Smart Mail connects to the **same IMAP/SMTP mailboxes** → no mail migration; both clients work in parallel during
   the pilot (4–6 weeks), Roundcube stays as fallback.
2. Import: contacts (Roundcube › Kontakty › Exportovať → vCard) → Smart Mail import; responses (Odpovede) and
   identities/signatures → admin import tool reading Roundcube DB tables `responses`/`identities` (optional, if DB
   access) or manual copy; user preferences: layout and "Konverzácie" mapped.
2b. Branches: the import tool lists Roundcube identities of each branch mailbox (today people switch between them as
   "signatures") and proposes one **person profile per identity** (name, function, phone parsed from the signature) +
   one branch signature template (common part); the admin confirms in Settings › Pobočky a osoby.
3. Filters and vacation are server-side Sieve scripts → keep working; Smart Mail edits the same scripts.
4. Rollout: week 1 mail only + AI summaries (shadow AI suggestions), week 2 AI drafts, week 3 Money actions;
   per-user feature flags.

---------------------------------------------------------------------------------------------------
## 7. Explicit non-goals
Calendar, chat/IM, task manager (use Money activities + follow-ups), CRM pipeline, marketing/newsletter campaigns
(separate tool), own mail server or spam engine, native mobile apps (PWA only), multi-company tenancy, UI languages
other than Slovak, AI auto-send, re-implementing Money editing screens (Smart Mail shows only the documents it
prepares — in the Money layout, DOCUMENTS_SPEC — and links to document numbers for everything else),
custom report builder, themes beyond light/dark.
