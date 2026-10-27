# SETTINGS_SPEC.md — Nastavenia: every section, every field (v2.10)

Binding specification of the settings area (screen W12 in SCREENS_SPEC, mobile M9). For each field: label (SK),
control, default, validation, help text (SK, shown under the field or in a tooltip ⓘ) and **scope** — where the value
is stored and who may change it. Figma frames: `W12-01 … W12-20` (+ sub-frames listed per section). If a field is not
here, it does not exist.

Scopes: **P** = person profile (PRODUCT_SPEC §2.0), **A** = login account, **M** = mailbox, **B** = branch,
**G** = global (whole company). Sections 01–09 are user sections (P/A/M scope; everybody sees them); sections 10–20
are admin sections (role admin; branch managers see section 11 for their own branch read/write).

---------------------------------------------------------------------------------------------------
## 0. Common behaviour

### 0.1 Layout (desktop)
Mirror of the customer's Roundcube settings (`design/reference/roundcube/03`, DECISIONS D19):
- G1 rail; no global top bar. Left column 248 px with the header "Nastavenia", search field "Hľadať v nastaveniach"
  and the section list with icons in Roundcube order: **Nastavenia** (01 — Roundcube's name for preferences),
  Priečinky (02), Identity (03a), Odpovede (04), Môj profil (03b — where Roundcube shows "Informácie o
  používateľovi"), Filtre (05), Mimo kancelárie (06), Nastavenia e-mail schránky (09b — as in Roundcube), AI asistent (07), Notifikácie (08),
  Bezpečnosť (09); divider
  label "SPRÁVA" with shield icon; admin sections 10–20. Active item highlighted.
- Middle column 280 px for sections with a list of items (01 subsections, 02 Priečinky, 03a Identity — rows
  "Meno <adresa>", 04 Odpovede, 05 Filtre, 10, 11, 12, 18). The right column header holds the list actions like
  Roundcube: **Vytvoriť** (`SquarePlus`) · **Vymazať** (`Trash2`).
- Right: form with the section title (`heading`), labels in the left half and fields in the right half (Roundcube),
  group titles `heading`, 24 px between groups; primary **"Uložiť"** with a check icon under the form (Roundcube).
  Long admin sections use tabs under the title (Money S4, AI – správa).
- Breadcrumb in the right column header: "Nastavenia › Money S4 › Tlačové zostavy". Deep link: `/settings/money/reports`.

### 0.2 Saving
| Field type | Save behaviour | Feedback |
|---|---|---|
| Switch, segmented control, select, radio (user sections 01, 07, 08) | **autosave** on change (debounce 400 ms), `PATCH` single key | small "Uložené ✓" next to the field for 2 s; on error the value reverts + inline error |
| Text in user sections | save on blur or `Ctrl+S` | same |
| Forms with several dependent fields (03, 04, 05, 06, all admin sections) | **explicit**: primary `Uložiť` (check icon) under the form like Roundcube, sticky at the bottom of the visible area when the form is longer than the screen, + "Neuložené zmeny" and `Zrušiť` next to it (disabled when clean or invalid) | toast "Nastavenia uložené"; field errors inline + summary at the top |
| Leaving a dirty form | Dialog "Máte neuložené zmeny" → Uložiť / Zahodiť / Zostať | |
| Concurrent edit (admin) | optimistic lock (`version`); 409 → banner "Medzitým to zmenil Peter Hudák – Načítať znova" | |
| Dangerous admin changes (marked ⚠ below) | confirm dialog + re-auth (password) when the last re-auth is older than 15 min | audit entry with before/after |

### 0.3 Inheritance and locks
Admin defaults (G) → branch (B) → person (P). A field limited by the admin shows a lock icon and tooltip "Nastavuje
správca" or "Maximum nastavil správca"; the user can choose only lower/allowed values. Reset link "Obnoviť
predvolené" per group.

### 0.4 Search in settings
Every field has an id (`prefs.list.density`) and keywords (SK synonyms, e.g. podpis → Identity, Môj profil, Pobočky ›
Podpis). Search shows matching fields with section path; selecting scrolls to the field and highlights it 2 s. Same
index is used by the command palette W11 (group "Nastavenia").

### 0.5 Validation messages (SK)
Povinné pole · Neplatný e-mail · Neplatné telefónne číslo (použite formát +421 …) · Hodnota musí byť medzi {min} a
{max} · Názov už existuje · Neplatné ID zostavy (očakáva sa GUID) · Server neodpovedá – skontrolujte adresu a port ·
Súbor je príliš veľký (max {n} MB) · Nepodporovaný formát súboru.

### 0.6 Audit
Every change in sections 10–20 and every change of 05/06 on shared mailboxes is written to the audit log (who = person
+ account, section, field, before → after). Section 19 shows it.

---------------------------------------------------------------------------------------------------
## 01 Nastavenia (P; Roundcube's "Nastavenia" = preferences) — frame `W12-01`, subsections a–e in the middle column

### 01a Používateľské rozhranie
| Pole | Ovládanie | Predvolené | Kontrola | Pomocný text | Scope |
|---|---|---|---|---|---|
| Jazyk rozhrania | select (disabled) | Slovenčina | — | Aplikácia je len v slovenčine. | G |
| Časové pásmo | select (IANA) | Europe/Bratislava | — | — | P |
| Formát dátumu | select: 25. 10. 2026 / 25.10.2026 / 2026-10-25 | 25. 10. 2026 | — | — | P |
| Formát času | segmented: 24 h / 12 h | 24 h | — | — | P |
| Vzhľad | segmented: Svetlý / Tmavý / Podľa systému | Podľa systému | — | — | P |
| Klasické zobrazenie | switch | vypnuté | — | Skryje AI triedenie, zhrnutia a asistenta – vyzerá ako Roundcube. Návrhy AI zostanú zbalené. | P |
| Po prihlásení otvoriť | select: Doručená pošta / Dnes | Doručená pošta | — | — | P |
| Úvodná prehliadka | button "Spustiť znova" | — | — | — | — |

### 01b Zobrazenie schránky
| Pole | Ovládanie | Predvolené | Kontrola | Pomocný text | Scope |
|---|---|---|---|---|---|
| Rozloženie | segmented: Tri stĺpce / Zoznam bez náhľadu | Tri stĺpce | — | — | P |
| Hustota zoznamu | segmented: Kompaktná / Pohodlná | Kompaktná | — | Kompaktná = dva riadky ako v Roundcube; Pohodlná pridá AI zhrnutie. | P |
| Zobraziť AI zhrnutie v zozname | switch | zapnuté | disabled in Klasické zobrazenie | — | P |
| Režim zoznamu | segmented: Zoznam / Konverzácie | Zoznam | — | Ako „Režim zoznamu“ v Roundcube (aj v dialógu Nastavenia zoznamu). | P |
| Zoraďovanie | select: Žiadne / Dátum prijatia / Dátum odoslania / Predmet / Od/Komu / Veľkosť / Kategória / Priorita | Dátum prijatia | — | — | P |
| Systém zoraďovania | segmented: vzostupne / zostupne | zostupne | — | — | P |
| Počet správ na stránku | select 25/50/100/200 | 50 | only Zoznam mode | — | P |
| Označiť ako prečítané | select: Ihneď / Po 3 sekundách / Nikdy | Po 3 sekundách | — | — | P |
| Po vymazaní alebo archivovaní otvoriť | select: Ďalšiu správu / Predchádzajúcu / Zoznam | Ďalšiu správu | — | — | P |
| Počet neprečítaných v názve okna | switch | zapnuté | — | — | P |
| Kontrolovať novú poštu vo všetkých priečinkoch | switch | vypnuté | — | Doručená pošta sa kontroluje vždy okamžite. | A |

### 01c Zobrazovanie správ
| Pole | Ovládanie | Predvolené | Kontrola | Pomocný text | Scope |
|---|---|---|---|---|---|
| Obrázky z internetu | select: Nikdy / Od známych odosielateľov / Vždy | Od známych odosielateľov | "Vždy" locked if admin forbids | Blokovanie chráni pred sledovaním. | P |
| Uprednostniť HTML | switch | zapnuté | — | — | P |
| Predvolená znaková sada | select | UTF-8 | — | — | P |
| Zobraziť prílohy pod správou | switch | zapnuté | — | — | P |
| Automaticky prekladať cudzojazyčné správy | switch | vypnuté | — | Tlačidlo Preložiť je dostupné vždy. | P |
| Jazyk prekladu | select | Slovenčina | — | — | P |

### 01d Vytváranie správ
| Pole | Ovládanie | Predvolené | Kontrola | Pomocný text | Scope |
|---|---|---|---|---|---|
| Formát správy | segmented: HTML / Čistý text | HTML | — | — | P |
| Písmo a veľkosť | select font (Inter, Arial, Times New Roman) + size 12–18 | Inter 14 | 12–18 | — | P |
| Citovanie pri odpovedi | select: Písať nad citáciu / pod citáciu / Necitovať | nad citáciu | — | — | P |
| Automaticky ukladať koncept | select: 30 s / 1 min / 5 min / Nikdy | 30 s | — | — | P |
| Oneskorenie odoslania (Späť) | slider 0–30 s, step 5 | 10 s | admin minimum may lock | Počas tohto času môžete odoslanie zrušiť. | P |
| Potvrdenie o doručení predvolene | switch | vypnuté | — | — | P |
| Pridať podpis pri odpovedi a preposlaní | switch | zapnuté | — | — | P |
| Okno písania | segmented: Celá plocha / Vyskakovacie okno | Celá plocha | — | — | P |
| Jazyk kontroly pravopisu | select: Podľa jazyka správy / SK / CZ / EN / DE | Podľa jazyka správy | — | — | P |
| Kontrola pred odoslaním | switch | zapnuté | locked on for "chýbajúca príloha" and "[[DOPLNIŤ]]" | Upozorní na chýbajúcu prílohu, iných príjemcov a nevyplnené údaje. | P |

### 01e Klávesové skratky
| Pole | Ovládanie | Predvolené | Kontrola | Pomocný text | Scope |
|---|---|---|---|---|---|
| Klávesové skratky zapnuté | switch | zapnuté | — | — | P |
| Zoznam skratiek | read-only table grouped (UX_SPEC §6) + button "Vytlačiť ťahák" | — | — | Skratky sú pre všetkých rovnaké. | — |

---------------------------------------------------------------------------------------------------
## 02 Priečinky (M) — frame `W12-02`
Like the customer's Roundcube (`design/reference/roundcube/07`): middle column = search field + list of all folders with
icons and a subscription switch on each row (special folders locked on); right column header toolbar **Vytvoriť ·
Vymazať · Vyprázdniť**; right: detail of the selected folder. Mailbox select on top if 2+.
| Pole | Ovládanie | Predvolené | Kontrola | Pomocný text | Scope |
|---|---|---|---|---|---|
| Názov | text | — | povinné, unikátne v nadradenom, bez znaku oddeľovača IMAP | — | M |
| Nadradený priečinok | select (tree) | — (koreň) | nie do seba ani podpriečinka | — | M |
| Odoberať (zobrazovať) | switch | zapnuté | special folders locked on | — | A |
| Súkromné – AI nespracúva | switch | vypnuté | — | Správy v tomto priečinku AI nečíta ani netriedi. | M |
| Štatistika | read-only: počet správ, neprečítané, veľkosť | — | — | — | — |
| Akcie | buttons: Vyprázdniť (confirm), Vymazať priečinok (confirm, nie pre špeciálne) | — | — | — | M |
Group "Špeciálne priečinky" (admin only, per mailbox): selects Koncepty, Odoslané, Nevyžiadaná pošta, Kôš, Archív
(default from IMAP SPECIAL-USE; ⚠ change).

---------------------------------------------------------------------------------------------------
## 03 Identity a Môj profil — frames `W12-03a` (Identity), `W12-03b` (Môj profil)

### 03a Identity (M; list of identities of the mailbox in the middle column)
| Pole | Ovládanie | Predvolené | Kontrola | Pomocný text | Scope |
|---|---|---|---|---|---|
| Zobrazované meno | text | from mailbox (e.g. "Smart s.r.o. – pobočka Senica") | povinné, max 100 | Toto meno vidí zákazník v poli Od. | M |
| E-mail | select of addresses allowed for the mailbox (admin) | adresa schránky | povinné | — | M |
| Organizácia | text | Smart s.r.o. | max 100 | — | M |
| Odpovedať na | e-mail | — | platný e-mail | — | M |
| Skrytá kópia | e-mail list | — | platné e-maily | Každá odoslaná správa pôjde aj na túto adresu. | M |
| Predvolená identita | switch | prvá identita | presne jedna predvolená | — | M |
| Podpis | branch mailbox: read-only preview "Podpis pobočky – mení správca" + link to 11; personal mailbox: **HTML editor ako v Roundcube**: WYSIWYG (B I U, zarovnanie, písmo, veľkosť, farba, odkaz, tabuľka, obrázok) + tlačidlo **`<>` Zdrojový kód** (dialóg s HTML, zvýraznenie syntaxe, Vložiť/Zrušiť) na vloženie vlastného HTML; **Vložiť obrázok** = nahrať súbor (PNG/JPG/GIF/SVG→PNG, max 200 kB, max 5 obrázkov) alebo zadať https URL; tabs SK / CZ / EN / DE | branch template / empty | HTML max 64 kB, obrázky max 200 kB, sanitizér ako 11c | Jazyk podpisu sa vyberie podľa jazyka správy. | M/P |

### 03b Môj profil (P — the active person)
| Pole | Ovládanie | Predvolené | Kontrola | Pomocný text | Scope |
|---|---|---|---|---|---|
| Meno, Priezvisko | text, text | from admin | povinné, max 50 | Zobrazí sa v podpise a pri priradení. | P |
| Funkcia | text | from admin | max 60 | Napr. obchod, vedúci pobočky. | P |
| Telefón, Mobil | tel | — | E.164 (+421 …) | — | P |
| Osobný e-mail | e-mail | — | platný e-mail | Len ak ho chcete mať v podpise. | P |
| Fotka | upload + crop 1:1 | iniciály | JPG/PNG, max 5 MB | — | P |
| Jazyky, ktorými komunikujem | multi-select SK/CZ/EN/DE/HU/PL | SK | — | AI ponúkne preklad do týchto jazykov. | P |
| Môj štýl písania pre AI | textarea + button "Vytvoriť z mojich odoslaných e-mailov" | prázdne | max 2 000 znakov | AI píše návrhy vaším štýlom. Vytvorí sa z posledných 200 správ, ktoré ste poslali. | P |
| Náhľad podpisu | preview with language tabs | — | — | Takto bude vyzerať váš podpis v e-mailoch pobočky. | — |

---------------------------------------------------------------------------------------------------
## 04 Odpovede (P personal / G shared) — frame `W12-04`
Middle: list with filter chips Moje / Zdieľané / Všetky, search, language tag on each item; "Nová odpoveď".
| Pole | Ovládanie | Predvolené | Kontrola | Pomocný text | Scope |
|---|---|---|---|---|---|
| Názov | text | — | povinné, unikátne v rozsahu, max 80 | — | P/G |
| Jazyk | select SK/CZ/EN/DE | SK | — | — | P/G |
| Text | rich editor + variable chips {meno} {firma} {cislo_faktury} {suma} {datum_splatnosti} {cislo_objednavky} {odpoveda} | — | povinné, max 20 kB; neznáma premenná = chyba | Premenné sa doplnia z e-mailu a z Money. | P/G |
| Zdieľaná pre všetkých | switch | vypnuté | role sales+ | Zdieľané odpovede vidia všetci. | G |
| Skratka | text (bez medzier) | — | unikátna, max 20 | V písaní napíšte /skratka. | P/G |
| Import z Roundcube | button (admin) | — | — | Načíta odpovede z databázy Roundcube. | G |

---------------------------------------------------------------------------------------------------
## 05 Filtre (M; server-side Sieve, same scripts as Roundcube) — frame `W12-05`
Middle: list of filters (drag to reorder, switch on/off per filter, ⋯ menu: Duplikovať, Vymazať). Right: editor.
| Pole | Ovládanie | Predvolené | Kontrola | Pomocný text | Scope |
|---|---|---|---|---|---|
| Názov filtra | text | — | povinné | — | M |
| Platí pre | radio: všetky správy / ak platí ktorákoľvek podmienka / ak platia všetky podmienky | všetky podmienky | — | — | M |
| Podmienky | repeatable row: Pole (Predmet, Od, Komu, Kópia, Komu alebo Kópia, Telo, Veľkosť, Hlavička…) · Operátor (obsahuje, neobsahuje, je, nie je, začína na, končí na, väčšie ako, menšie ako) · Hodnota | 1 riadok | ≥ 1 podmienka (okrem "všetky správy"); veľkosť v kB | — | M |
| Akcie | repeatable row: Presunúť do (folder select), Kopírovať do, Presmerovať na, Poslať kópiu na, Odmietnuť so správou, Vymazať, Označiť ako prečítané, Označiť príznakom, Zastaviť ďalšie pravidlá | 1 riadok | ≥ 1 akcia; e-mail platný | Filtre fungujú na serveri – aj keď je aplikácia zatvorená, aj v Roundcube. | M |
| Odkaz | link "AI pravidlá (podľa významu)" → 17 | — | — | — | — |
Shared/branch mailbox: banner "Filter platí pre celú pobočku". Save → ManageSieve upload; syntax error from server
shown under the form.

---------------------------------------------------------------------------------------------------
## 06 Mimo kancelárie (M) — frame `W12-06`
| Pole | Ovládanie | Predvolené | Kontrola | Pomocný text | Scope |
|---|---|---|---|---|---|
| Automatická odpoveď | switch | vypnuté | — | Na pobočkovej schránke odpovedá za celú pobočku. | M |
| Od – do | date-time range | dnes – (prázdne) | koniec po začiatku | Bez dátumu do platí, kým ju nevypnete. | M |
| Predmet | text | Mimo kancelárie: {predmet} | max 120 | — | M |
| Text odpovede | rich editor, tabs SK / EN / DE | predvolený text SK | povinné SK | Odpoveď sa odošle v jednom e-maile – slovensky, potom anglicky a nemecky. | M |
| Odpovedať tomu istému odosielateľovi najviac raz za | select 1 / 3 / 7 dní | 7 dní | — | — | M |
| Pre adresy | multi-select identities of the mailbox | všetky | ≥ 1 | — | M |
| Neodpovedať na hromadné a automatické správy | switch (locked on) | zapnuté | — | — | M |
| Počas neprítomnosti prideliť nové e-maily | select person / Nikomu | Nikomu | — | AI nové e-maily pridelí vybranému kolegovi. | M |

---------------------------------------------------------------------------------------------------
## 07 AI asistent (P) — frame `W12-07`
| Pole | Ovládanie | Predvolené | Kontrola | Pomocný text | Scope |
|---|---|---|---|---|---|
| AI asistent zapnutý | switch | zapnuté | admin may lock off | Vypnutím zmiznú návrhy aj asistent; triedenie beží ďalej pre ostatných. | P |
| Samostatnosť | matrix: rows = actions (AI_ASSISTANT §1), columns = Vypnuté / Len navrhnúť / Pripraviť na schválenie / Urobiť a oznámiť / Urobiť potichu (radio) | AI_ASSISTANT §1 defaults | **set by each login itself, no admin maximum (DECISIONS D8)**; hard rule in code: external send and Money writes max "Pripraviť na schválenie" (locked for everybody) | Koľko smie AI urobiť sama. Odoslanie von a zápis do Money vždy schvaľuje človek. | A (prihlásenie / účet – platí pre všetky osoby na tomto prihlásení) |
| Oslovovanie zákazníkov | segmented: Vykanie / Tykanie / Podľa zákazníka | Vykanie | — | — | P |
| Zhrnutia v zozname | switch | zapnuté | — | — | P |
| Ranný prehľad Dnes – čas | time | 6:30 | 5:00–11:00 | — | P |
| Poslať prehľad aj e-mailom | switch | vypnuté | — | — | P |
| Dni prehľadu | weekday chips | Po–Pi | ≥ 1 | — | P |
| Pripomenúť, ak zákazník neodpovie do | select 2 / 3 / 5 / 7 pracovných dní | 3 | — | Ponuky a otázky bez odpovede sa zobrazia v „Čakám na odpoveď“. | P |
| História asistenta | button "Vymazať históriu konverzácií" (confirm) | — | — | — | P |

---------------------------------------------------------------------------------------------------
## 08 Notifikácie (P) — frame `W12-08`
| Pole | Ovládanie | Predvolené | Kontrola | Pomocný text | Scope |
|---|---|---|---|---|---|
| Notifikácie na tomto zariadení | status + button "Povoliť notifikácie" / "Vypnúť na tomto zariadení" | — | browser permission | Na mobile najprv pridajte aplikáciu na plochu. | device |
| Typy × kanály | table rows: Urgentné, Pridelené mne, Zmienka v poznámke, Na schválenie (súhrnne najviac 1× za 30 min), Dodací list na kontrolu*, Objednávka na kontrolu*, Zápis do Money zlyhal*, Synchronizácia zlyhala (admin); columns V aplikácii / Push / E-mail (checkbox) | Urgentné, Pridelené, Zmienka: všetky okrem e-mailu; ostatné V aplikácii + Push | *only for roles that can act | — | P |
| Tichý režim | switch + time range | zapnutý 18:00–7:00 | koniec ≠ začiatok | — | P |
| Urgentné aj v tichom režime | switch | vypnuté | — | — | P |
| Zvuk v aplikácii | switch | zapnuté | — | — | P |
| Denný súhrn e-mailom | switch | vypnuté | — | — | P |

---------------------------------------------------------------------------------------------------
## 09 Bezpečnosť (A/P) — frame `W12-09`
| Pole | Ovládanie | Predvolené | Kontrola | Pomocný text | Scope |
|---|---|---|---|---|---|
| Prihlásenie | info card | — | — | Prihlasujete sa e-mailom a heslom k pošte. Heslo sa mení na mailovom serveri; potom sa prihláste znova. | A |
| Dvojstupňové overenie | button "Zapnúť" → dialog (QR, kód, 10 záložných kódov) / "Vypnúť" (re-auth) | vypnuté | only personal accounts | — | A |
| Aktívne relácie | table: Zariadenie, Prehliadač, Miesto (mesto z IP), Posledná aktivita, Osoba; action Odhlásiť; button "Odhlásiť všetky ostatné" | — | — | — | A |
| Zapamätané zariadenia | list with "Zabudnúť" | — | — | Zabudnuté zariadenie si pri ďalšom prihlásení nebude pamätať osobu. | A |
| Mobilné zariadenia s notifikáciami | list with "Odobrať" | — | — | — | P |

### 09b Nastavenia e-mail schránky (u poskytovateľa) — frame `W12-09b`
In the customer's Roundcube this section comes from the hosting provider's plugin (server mail2.nameserver.sk;
`design/reference/roundcube/08`): Informácie o e-mail schránke používateľa (schránka, server, posledné prihlásenie,
hlavný e-mail, E-mail presmerovania), Zmena hesla, Ostatné nastavenia, Automatická odpoveď, GEOIP ochrana. These are
settings **of the mail server, not of Roundcube** — Smart Mail has no API to change them, so it shows what it knows
and links to the provider (DECISIONS D20). Same position and name in the section list as in Roundcube (after Mimo
kancelárie).
| Pole | Ovládanie | Predvolené | Kontrola | Pomocný text | Scope |
|---|---|---|---|---|---|
| Informácie o schránke | read-only: E-mailová schránka, Server (IMAP host), Posledné prihlásenie (v Smart Mail), Úložné miesto (QUOTA) | — | — | — | M |
| Zmena hesla, presmerovanie, ostatné nastavenia, GEOIP ochrana | button "Otvoriť správu schránky u poskytovateľa" (URL from SETTINGS 12 "Správa schránky u poskytovateľa") | — | — | Tieto nastavenia sú na mailovom serveri. Po zmene hesla sa v Smart Mail prihláste novým heslom. | — |
| Automatická odpoveď | info: "Používajte Mimo kancelárie (06) – je to tá istá automatická odpoveď na serveri." + link to 06 | — | — | Nezapínajte obe naraz, zákazník by dostal dve odpovede. | — |

---------------------------------------------------------------------------------------------------
## 10 Používatelia a role (G, admin) — frame `W12-10`
Middle: list of accounts (Prihlasovací e-mail, Typ: Osobný / Pobočkový / Zdieľaný, Osoby, Posledné prihlásenie,
Stav). Right: detail.
| Pole | Ovládanie | Predvolené | Kontrola | Pomocný text | Scope |
|---|---|---|---|---|---|
| Prihlasovací e-mail | e-mail (read-only after create) | — | must exist on the mail server ("Overiť" = test login with password, password not stored for personal accounts) | — | G |
| Typ účtu | segmented: Osobný / Pobočkový | Osobný | Pobočkový requires a branch (11) | Pobočkový = viac ľudí pod jedným e-mailom, s výberom „Kto ste?“. | G |
| Osoba (len osobný účet) | person form (as 11 Osoby) | — | — | — | G |
| Rola (osobný účet) | select: Správca / Obchod / Sklad / Účtovníctvo / Len čítanie | Obchod | at least one active Správca must remain ⚠ | — | G |
| Prístup k schránkam | table mailbox × Čítať / Odosielať ako | own mailbox | — | — | G |
| Prihlásenie cez Microsoft/Google | switch + linked identity | vypnuté | admins only | — | G |
| Vyžadovať 2FA | switch | vypnuté (zapnuté pre správcov) | — | — | G |
| Stav | switch Aktívny; button "Odhlásiť zo všetkých zariadení" ⚠ | aktívny | — | Deaktivovaný účet sa nemôže prihlásiť; história zostáva. | G |
| Matica oprávnení | read-only table (PRODUCT_SPEC §4) | — | — | — | — |

---------------------------------------------------------------------------------------------------
## 11 Pobočky a osoby (B, admin; branch manager for own branch) — frames `W12-11a` Údaje, `11b` Osoby, `11c` Podpis, `11d` Prihlasovanie, `11e` Money
Middle: list of branches (Názov, Schránka, Osoby, Vedúci) + "Pridať pobočku". Right: tabs.

**11a Údaje pobočky**
| Pole | Ovládanie | Predvolené | Kontrola | Pomocný text | Scope |
|---|---|---|---|---|---|
| Názov pobočky | text | — | povinné, unikátne | Napr. Pobočka Senica. | B |
| Schránka pobočky | select (from 12) | — | povinné, jedna schránka = jedna pobočka | — | B |
| Adresa | text area | — | max 200 | Použije sa v podpise. | B |
| Telefón pobočky | tel | — | E.164 | — | B |
| Otváracie hodiny | text | — | max 120 | Napr. Po–Pi 7:00–15:30. | B |
| Logo do podpisu | upload | firemné logo (`design/brand/logo-smart.png`) | PNG/SVG, max 200 kB | — | B |
| Priečinky pobočky | multi-select priečinkov zdieľaných schránok (napr. „Senica“ v eshop@) | — | — | E-maily, ktoré sem presúvajú vaše filtre, dostanú túto pobočku (doklady, objednávky, podpis). | B |

**11b Osoby** (table: fotka, meno, funkcia, mobil, rola, vedúci, aktívna; row → drawer)
| Pole | Ovládanie | Predvolené | Kontrola | Pomocný text | Scope |
|---|---|---|---|---|---|
| Meno, Priezvisko | text | — | povinné | — | B |
| Funkcia | text | — | max 60 | — | B |
| Telefón, Mobil | tel | — | E.164 | — | B |
| Fotka | upload + crop | iniciály | max 5 MB | — | B |
| Rola | select (as 10) | Obchod | — | Určuje, čo osoba smie (napr. schvaľovať zápisy do Money). | B |
| Vedúci pobočky | switch | vypnuté | ≥ 1 vedúci (warning if 0) | Vedúci vidí Prehľad pobočky a môže meniť osoby. | B |
| Obchodník v Money | select (Money staff via REST) | — | — | Zapíše sa do objednávok, ktoré osoba schváli. | B |
| Pôsobí aj na pobočkách | multi-select branches | — | — | Osoba sa zobrazí aj vo výbere iných pobočiek. | B |
| Aktívna | switch | zapnuté | ≥ 1 aktívna osoba na pobočke | Neaktívna osoba sa nezobrazí vo výbere „Kto ste?“. | B |
| Odstrániť osobu | button ⚠ (confirm with the name) | — | not the last active person of the branch; history (audit, sent mail) keeps the name | Osobu môžete aj len deaktivovať. | B |

**11c Podpis**
| Pole | Ovládanie | Predvolené | Kontrola | Pomocný text | Scope |
|---|---|---|---|---|---|
| Šablóna podpisu | **HTML editor ako v Roundcube**: WYSIWYG (B I U, zarovnanie, písmo, veľkosť, farba, odkaz, tabuľka, obrázok) + tlačidlo **`<>` Zdrojový kód** (dialóg s HTML, zvýraznenie syntaxe, Vložiť/Zrušiť) na vloženie vlastného HTML; **Vložiť obrázok** = nahrať súbor (PNG/JPG/GIF/SVG→PNG, max 200 kB, max 5 obrázkov) alebo zadať https URL; tabs SK / CZ / EN / DE, variable chips {meno} {priezvisko} {funkcia} {telefon} {mobil} {email_osobny} {email_pobocky} {pobocka} {adresa_pobocky} {telefon_pobocky} {oteviracie_hodiny} {web} {fotka} {logo} | predvolená šablóna **„Karta“ – rovnaká ako dnešný HTML podpis v Roundcube**: vľavo fotka osoby v šesťuholníku (80 px; bez fotky iniciály), v strede MENO PRIEZVISKO (veľké písmená, tučné), funkcia (modrá), tenká modrá čiara, riadok telefón + adresa pobočky, riadok e-mail pobočky + web, vpravo logo SMART s textom „Spojovací materiál“; nad ňou „S pozdravom,“. Druhá šablóna „Text“ (S pozdravom / meno / funkcia · mobil / Smart s.r.o. – pobočka / adresa · telefón) | SK povinná; neznáma premenná = chyba; HTML max 64 kB; HTML sa vyčistí bezpečným sanitizérom (povolené tabuľky, inline štýly, `img`, odkazy; zakázané skripty, formuláre, iframe, externé CSS) a pri ukladaní sa ukáže, čo sa odstránilo | Prázdne premenné sa v podpise vynechajú aj s oddeľovačom. Vlastné HTML vložte cez <> Zdrojový kód. | B |
| Náhľad | person select + language select → live render | prvá osoba, SK | — | — | — |
| Obnoviť predvolenú šablónu | button (confirm) | — | — | — | B |

**11d Prihlasovanie**
| Pole | Ovládanie | Predvolené | Kontrola | Pomocný text | Scope |
|---|---|---|---|---|---|
| Opýtať sa „Kto ste?“ po nečinnosti | select: Nie / 30 / 60 / 120 min | Nie | — | — | B |
| Zostať prihlásený na zariadení | select 1 / 7 / 30 dní | 30 dní | — | — | B |
| Prehľad pobočky – upozorniť na nevybavené po | select 2 / 4 / 8 h | 4 h | — | — | B |

**11e Money (pobočka)** — admin only (branch manager read-only). **All values are dropdowns loaded live from Money
codebooks (never typed codes)**; each option shows `Kód – Názov`, the list has a search box and a "Načítať znova z
Money" link; a value that disappeared from Money is shown red "už neexistuje v Money". Data: `Centres`, `PriceLists`,
`Warehouses`, `NumericalSeries` (MONEY_API §5.10; `money_probe.py --branches` lists them in advance).
| Pole | Ovládanie | Predvolené | Kontrola | Pomocný text | Scope |
|---|---|---|---|---|---|
| Stredisko (číslo pobočky) | select (`Centres`) | — | **povinné** pre zápisy do Money ⚠ | Všetky doklady z tejto pobočky sa zapíšu pod toto stredisko. | B |
| Cenník pobočky | select (`PriceLists`; today pairs per branch `10-bez DPH`/`10-s DPH` … `40-…`, plus `13 PKT`, `99 Externý sklad`, `A1 - 100%`, `A2 - 70%`, `A3 - 30%`, `MPC` — D12) | — (admin picks; sample Senica = `20-bez DPH – Senica bez DPH`) | **povinné** ⚠ | Ceny v ponukách a objednávkach a cenník na položkách dokladov. Vyberte cenník pobočky, napr. „20-bez DPH – Senica bez DPH“. | B |
| Sklad pobočky | select (`Warehouses` — today 10 Trnava, 20 Senica, 30 Nitra, 40 Trenčín, 99 Externý sklad; D4, D11, D18 — 99 is listed like every warehouse but is never preselected or suggested as a default; choosing it shows the info "99 Externý sklad nie je sklad pobočky") | predvolený sklad zvoleného cenníka (`PriceList.VychoziSklad_ID`) | **povinné**; upozornenie, ak sa líši od skladu cenníka | Sem sa prijíma tovar z dodacích listov; zapíše sa aj na položky objednávok. | B |
| Číselné rady pobočky | table: Typ dokladu (Dodací list prijatý, Objednávka prijatá, Ponuka vydaná, Reklamácia) → Číselný rad (select) | prázdne = firemné z 13c | — | Vyplňte, ak má pobočka vlastné rady. | B |
| Vzorový dodací list pobočky | read-only card + "Vybrať iný" (select from the last 20 received delivery notes of this centre in Money, shows Číslo · Dodávateľ · Dátum) | posledný DL prijatý tejto pobočky vytvorený v Money | **povinné** pre príjem tovaru ⚠ | Z neho sa preberú hodnoty, ktoré Money API nemá v číselníkoch: Druh pohybu („obstaranie“), Druh skl. pohybu („príjem“), Typ ceny („Iba základ“), Druh položky („tovar“), Registrácia k DPH. | B |
| Overiť | button "Overiť nastavenie v Money" → checks that the centre, price list, warehouse and series exist and are active, that a template delivery note exists, and shows 3 sample prices from the price list | — | — | — | — |
Change of any field ⚠ = confirm + audit; drafts already prepared keep their values (shown with a hint "pripravené
pred zmenou nastavenia pobočky").

---------------------------------------------------------------------------------------------------
## 12 Schránky (G, admin) — frame `W12-12`
Middle: list (Adresa, Typ, stav pripojenia dot, Posledná synchronizácia, Kvóta). Right:
| Pole | Ovládanie | Predvolené | Kontrola | Pomocný text | Scope |
|---|---|---|---|---|---|
| Adresa schránky | e-mail | — | povinné, unikátne | — | M |
| Typ | segmented: Osobná / Zdieľaná / Pobočková | Osobná | Pobočková → link to 11 | — | M |
| IMAP server, port, šifrovanie | text, number, select SSL/TLS / STARTTLS | port 993, SSL/TLS | port 1–65535 | Rovnaké údaje ako v Roundcube. | M |
| SMTP server, port, šifrovanie | text, number, select | port 465 SSL/TLS (587 STARTTLS) | — | — | M |
| Používateľ a heslo | text + password (masked, "Zmeniť") | adresa schránky | povinné ⚠ | Uloží sa šifrovane; po zmene hesla na serveri ho aktualizuje prvé prihlásenie. | M |
| ManageSieve (filtre, mimo kancelárie) | switch + server, port | zapnuté, 4190 | — | — | M |
| Otestovať pripojenie | button → checklist IMAP / SMTP / Sieve / SPECIAL-USE / QUOTA / IDLE | — | — | — | — |
| AI spracovanie schránky | switch | zapnuté | — | Vypnuté = schránka funguje ako v Roundcube bez AI. | M |
| Prístupy | table account/person × Čítať / Odosielať ako | — | — | — | M |
| Správa schránky u poskytovateľa | URL | — (pre mail2.nameserver.sk vyplní správca) | https URL | Odkaz pre Nastavenia e-mail schránky (09b): zmena hesla, presmerovanie, GEOIP. | M |
| Odpojiť schránku | button ⚠ (confirm with address typed) | — | — | Pošta na serveri zostane, zmažú sa len údaje v Smart Mail. | M |

---------------------------------------------------------------------------------------------------
## 13 Money S4 (G, admin) — frame `W12-13` with tabs a–f
**13a Prepojenie**
| Pole | Ovládanie | Predvolené | Kontrola | Pomocný text | Scope |
|---|---|---|---|---|---|
| Stav | status card: Money Bridge, agenda TEST / OSTRÁ, verzia API, odozva, posledná synchronizácia, button "Otestovať" | — | — | — | — |
| Zápisy do Money povolené | switch ⚠ | vypnuté | enabling on OSTRÁ agenda requires typing "OSTRÁ" | Hlavný vypínač všetkých zápisov (dodacie listy prijaté, objednávky, ponuky, reklamácie, firmy). | G |
| Výsledok testovacieho skriptu | upload report.md / orders.md → parsed summary table | — | .md, max 1 MB | Výsledok money_probe.py z testovacej agendy. | G |

**13b Tlačové zostavy** — table rows: Faktúra vydaná, Zálohová faktúra vydaná, Dobropis, Cenník, Ponuka vydaná
(only when the implementer adds an offer report, D5); columns SK / EN / DE: text field "ID zostavy" (GUID or integer config id) + button "Vyskúšať PDF" (opens
PDF of the latest document). Validation: GUID/integer format; empty language falls back to SK. Info line: "Faktúry
sa v Smart Mail nikdy nevytvárajú ani neprekresľujú – k e-mailu sa priloží vždy originálne PDF z Money. Dodacie
listy a objednávky Money cez API ako PDF neposkytuje." (DOCUMENTS_SPEC §6, MONEY_API §5.9b).

**13c Predvolené hodnoty dokladov** (company defaults; **branch values from 11e — stredisko, cenník, sklad, číselné
rady — always win**; extra row "Centrála" = branch profile used for central mailboxes such as info@) — table rows:
Dodací list prijatý, Objednávka prijatá, Ponuka vydaná (after `IssuedOffer`, D5), Reklamácia prijatá; columns: Číselný rad, Predkontácia, Členenie DPH, Stredisko, Zákazka, Činnosť,
Sklad — each a select loaded from Money codebooks (search inside, shows code + name); cells not applicable are
disabled. Switch "Šablóna = posledný doklad partnera" (default on; help "Ak má partner starší doklad, prevezmú sa
hodnoty z neho.").

**13d Aktivity**
| Pole | Ovládanie | Predvolené | Kontrola | Pomocný text | Scope |
|---|---|---|---|---|---|
| Zapisovať aktivitu po odoslaní e-mailu zákazníkovi | switch | zapnuté | — | — | G |
| Typ aktivity – odoslaný e-mail / upomienka / potvrdenie objednávky | 3 selects (TypeOfActivity) | — | povinné ak zapnuté | — | G |

**13e Synchronizácia**
| Pole | Ovládanie | Predvolené | Kontrola | Pomocný text | Scope |
|---|---|---|---|---|---|
| Interval synchronizácie | select 5 / 15 / 30 / 60 min | 15 min | — | Firmy, artikle, kódy dodávateľov, číselníky. | G |
| Synchronizovať teraz | button + progress | — | — | — | — |
| História | table last 20 runs (čas, trvanie, zmenené záznamy, chyby) | — | — | — | — |

**13f Vrátenie zápisov**
| Pole | Ovládanie | Predvolené | Kontrola | Pomocný text | Scope |
|---|---|---|---|---|---|
| Okno na vrátenie zápisu | select 5 / 15 / 30 min | 15 min | — | Počas tohto času sa dá nový doklad v Money zmazať, ak ešte nebol spracovaný. | G |

---------------------------------------------------------------------------------------------------
## 14 Nákup a sklad (G, admin) — frame `W12-14`
| Pole | Ovládanie | Predvolené | Kontrola | Pomocný text | Scope |
|---|---|---|---|---|---|
| Čo sa zapisuje do Money | info (read-only): "Len dodací list prijatý – faktúru prijatú Smart Mail nerieši" (DECISIONS D7) | — | — | — | — |
| Predvolený sklad príjmu | info: sklad pobočky z 11e (10 Trnava, 20 Senica, 30 Nitra, 40 Trenčín) | — | — | — | — |
| Sklad podľa dodávateľa / kategórie | table (Dodávateľ alebo kategória → Sklad) | — | — | — | G |
| Upozorniť na odchýlku ceny nad | number % | 10 % | 0–100 | Porovnáva sa s poslednou nákupnou cenou od dodávateľa. | G |
| Upozorniť na odchýlku množstva oproti objednávke | number % | 0 % (každá) | 0–100 | — | G |
| Kto potvrdzuje párovanie položiek | multi-select roles | Sklad, Správca | ≥ 1 | — | G |
| Dátum vystavenia dodacieho listu | segmented: Dátum dokladu dodávateľa / Dátum schválenia | Dátum dokladu dodávateľa | — | Pole „Vystavenie“ na dodacom liste prijatom. | G |
| Dátum a čas skladového pohybu | info (read-only): "Okamih zápisu do Money (schválenie)" | — | — | Dátum a čas „Sklad. pohybu“ a „Účt. prípadu“ = kedy Smart Mail doklad zapísal do Money (DECISIONS D13). | — |
| Poplatky na dokladoch dodávateľa (doprava, balné) | info (read-only): "Nezapisujú sa – zobrazia sa v záložke Poplatky" | — | — | Ak treba, doplňte ich v Money (DECISIONS D14). | — |
| Vratky | info (read-only): "Vratky sa robia len v Money" | — | — | DECISIONS D15. | — |
| Kódy dodávateľov (naučené) | table: Dodávateľ, Kód dodávateľa, Náš artikel, Prepočet jednotky, Potvrdil, Dátum, Použité ×; search, filter dodávateľ; row drawer edit; delete (confirm); Export CSV | — | kód unikátny v rámci dodávateľa | Potvrdené párovania z faktúr. Export môžete nahrať do kariet artiklov v Money. | G |

---------------------------------------------------------------------------------------------------
## 15 Objednávky (G, admin) — frame `W12-15` (full rules: ORDERS_SPEC §16)
| Pole | Ovládanie | Predvolené | Kontrola | Pomocný text | Scope |
|---|---|---|---|---|---|
| Číselný rad objednávok prijatých | select (NumericalSeries) | — | povinné | — | G |
| Stredisko / Zákazka / Činnosť | 3 selects | — | — | — | G |
| Tolerancia ceny zákazníka | number % + number €/ks | 0,5 % · 0,0005 € | 0–20 % | Väčší rozdiel medzi cenou zákazníka a našou cenou sa zobrazí ako upozornenie. | G |
| Kontrola kreditu | segmented: Vypnutá / Upozorniť / Blokovať | Upozorniť | — | — | G |
| Upozorniť na faktúry po splatnosti staršie ako | number dní | 14 | 0–365 | — | G |
| Akceptovať normové ekvivalenty automaticky | switch | vypnuté | — | DIN ↔ ISO ekvivalent inak vždy potvrdí človek. | G |
| Spôsoby dopravy | table: Text v objednávke (napr. „kuriér“, „osobný odber“) → Spôsob dopravy v Money (select) | kuriér, osobný odber, naša doprava | text unikátny | — | G |
| Doprava ako položka | switch + Artikel (select) + Hranica bez dopravy (€) | vypnuté | artikel povinný ak zapnuté | — | G |
| Tlačiť pokyny zákazníka na doklady | switch | zapnuté | — | Atest 3.1, balenie a pod. sa vytlačia na dodacom liste. | G |
| Šablóny potvrdenia objednávky | editor, tabs SK / CZ / EN / DE, variables {cislo} {cislo_zakaznika} {tabulka} {zmeny} {doprava} {splatnost} {suma} | predvolené texty | SK povinná | Tabuľku a zmeny doplní systém. | G |
| Prikladať PDF potvrdenia | switch | vypnuté | — | — | G |
| Pripraviť potvrdenie hneď po vytvorení | switch | zapnuté | — | — | G |
| Ignorovať odosielateľov (e-shop) | chips (e-mail or @doména) | — | platný e-mail/doména | Objednávky z e-shopu prídu do Money cez e-shop, Smart Mail ich nespracuje. | G |
| Upozorniť na nevyriešenú objednávku po | select 2 / 4 / 8 / 24 h | 4 h | — | — | G |
| Režim zápisu ceny | radio: Hotová cena / Cena + zľava (+ probe result shown) | podľa testu | ⚠ | Overené testom dvojitej zľavy. | G |
| Tieňový režim objednávok | switch + accuracy card (zhoda riadkov %, chyby v cene/množstve, dni) + button "Zapnúť vytváranie" (enabled at ≥ 95 % and 0 errors) | zapnutý | ⚠ | — | G |
Per customer overrides live in W9b (SCREENS_SPEC).

---------------------------------------------------------------------------------------------------
## 16 Katalóg a ceny (G, admin) — frame `W12-16`
| Pole | Ovládanie | Predvolené | Kontrola | Pomocný text | Scope |
|---|---|---|---|---|---|
| Zásoba v ponukách | info (read-only): "Zobrazuje sa zásoba všetkých skladov z Money" | — | — | DECISIONS D18 – vyberiete správny sklad sami. Objednávky zásoby neriešia (D6). | — |
| Poradie zdrojov cien | sortable list: Cena zákazníka z Money / Cena z prijatej ponuky / Posledná predajná cena (len informácia) | v tomto poradí | — | — | G |
| E-shop feed (obrázky, popisy) | URL + interval | — | platná URL | Ceny a zásoby sa berú z Money, z e-shopu len obrázky a popisy. | G |
| Číslovanie ponúk | info (read-only): "Číslo pridelí Money (rad ponúk vydaných)" | — | — | DECISIONS D5 | — |
| Platnosť ponuky | number dní | 14 | 1–180 | — | G |
| Platobné podmienky / Dodacie podmienky | textarea × 2 | predvolené texty | max 1 000 | Vložia sa do PDF ponuky. | G |
| Vzhľad PDF ponuky | read-only info "Ako tlačová zostava Money „Ponuka vystavená“" + button "Náhľad" (renders the fixture with live company data) | pevný (DOCUMENTS_SPEC §4) | — | Rozloženie, písmo a farby sú rovnaké ako v Money; nastaviť sa dá len obsah nižšie. | G |
| Hlavička tlačových dokladov | form: Názov firmy, Ulica, PSČ, Mesto, IČO, DIČ, IČ DPH, Tel., Fax, text o zápise v OR, web, logo (upload) | z Money (údaje vlastnej firmy z posledného dokladu) + logo zo zostavy Money | IČO 8 číslic, IČ DPH SK + 10 číslic | Rovnaké údaje ako v hlavičke dokladov z Money. | G |
| Text pod tabuľkou ponuky | textarea SK / EN / DE + odkaz na VOP (document from 18) | prázdne | max 1 000 | Napr. dodacia lehota, platobné podmienky. | G |
| Riadok systému v päte | text | „Spracované systémom Smart Mail · ceny a zásoby z Money S4“ | max 120 | Zobrazí sa pod pätou ako v Money. | G |
| Zobraziť kód zákazníka pod názvom položky | switch | vypnuté | — | „Váš kód: …“ ak ho zákazník použil v dopyte. | G |
| Tabuľka DIN ↔ ISO ekvivalentov | editable table: DIN, ISO, Rozdiel (text) | AI_ASSISTANT §8 list | dvojica unikátna | Používa sa pri ponukách a objednávkach. | G |

---------------------------------------------------------------------------------------------------
## 17 AI – správa (G, admin) — frame `W12-17` with tabs a–f
**17a Poskytovateľ a rozpočet**: Poskytovateľ (segmented Anthropic / AWS Bedrock EÚ; ⚠), Región (select, eu-central-1),
Modely (read-only list from env with purpose labels), Denný rozpočet (number USD, default 10, 1–500), Upozorniť pri
(% , 80), Pri vyčerpaní (select: Triediť len podľa pravidiel / Vypnúť AI; default first), Uchovávať záznamy AI (select
30 / 90 / 365 dní; 90).
**17b Samostatnosť AI**: no admin maximum — each login sets it in 07 (DECISIONS D8). This tab only shows a read-only
overview per login and the hard rule "Odoslanie mimo firmy a zápis do Money vždy schvaľuje človek".
**17c Kategórie**: table (Názov, Farba, Zapnutá, Popis pre AI – textarea used in the classify prompt, Počet za 30 dní);
add custom category (max 15 categories); VIP zákazníci (multi-select Money companies; urgent priority).
**17d Štýl a znalosti**: Štýlová príručka firmy (rich text: oslovenie, podpis, čo nesľubovať, zakázané frázy), Znalosti
(cards list: Názov, Text, Platné do, Tagy; add/edit/delete; used by retrieval), Knižnica (link to 18).
**17e Pravidlá**: list (text pravidla v slovenčine → prevedená podoba "Ak … tak …", Zapnuté, Autor, Posledné použitie);
"Nové pravidlo" (textarea → AI preview of structured rule → Uložiť); "Vyskúšať na posledných 50 e-mailoch" shows which
messages would match.
**17f Tieňový režim, spotreba a presnosť**: switches per feature (AI návrhy odpovedí, Príjem tovaru (dodacie listy), Objednávky,
Ponuky) with accuracy cards; charts: náklady za deň (30 dní), schválené bez úprav %, presnosť kategórií (tabuľka zámen),
top dôvody zamietnutia. Read-only, export CSV.

---------------------------------------------------------------------------------------------------
## 18 Knižnica dokumentov (G, admin) — frame `W12-18`
| Pole | Ovládanie | Predvolené | Kontrola | Pomocný text | Scope |
|---|---|---|---|---|---|
| Typy dokumentov | table: Názov, Platnosť povinná (switch), Upozorniť pred koncom (dni) | VOP, Reklamačný poriadok, Katalóg, Technický list, Atest 3.1, Certifikát | názov unikátny | — | G |
| Kto môže nahrávať | multi-select roles | Správca, Obchod | ≥ 1 | — | G |
| Upozornenie na končiace certifikáty | multi-select persons | správcovia | — | — | G |
| Uchovávanie dokumentov po skončení platnosti | select 1 / 3 / 5 / 10 rokov | 5 rokov | — | — | G |

---------------------------------------------------------------------------------------------------
## 19 Audit log (G, admin; read-only) — frame `W12-19`
Filters: Osoba, Účet, Oblasť (Pošta, Money, Nastavenia, Prihlásenie, AI), Akcia, Objekt (text), Obdobie. Table: Čas,
Osoba (avatar), Účet, Akcia, Objekt (link), Detail (expand: before → after, IP, zariadenie). Export CSV (current filter).
Info: "Záznamy sa nedajú upraviť ani zmazať."

---------------------------------------------------------------------------------------------------
## 20 Systém (G, admin) — frame `W12-20`
| Pole | Ovládanie | Predvolené | Kontrola | Pomocný text | Scope |
|---|---|---|---|---|---|
| Interné domény | chips | smartsro.sk | platná doména | E-maily na tieto domény sú interné (iné pravidlá AI a upozornení). | G |
| Funkcie (feature flags) | table: Funkcia (AI návrhy, Asistent, Príjem tovaru (dodacie listy), Objednávky, Ponuky, Prehľad pobočky) × Zapnuté pre (Všetci / vybrané pobočky / vybrané osoby) | podľa fázy zavedenia | ⚠ | — | G |
| Zálohy | status card (posledná záloha, veľkosť, ďalšia, posledný test obnovy) | — | — | — | — |
| Úložisko | usage bars (správy, prílohy, dokumenty, AI záznamy) | — | — | — | — |
| Stav synchronizácie pošty | table per mailbox (posledná synchronizácia, chyby, IDLE) | — | — | — | — |
| Údržba | buttons: Preindexovať hľadanie · Znovu spracovať AI za posledných (1 / 7 / 30) dní · Vyprázdniť cache Money — each ⚠ confirm | — | — | — | G |
| Oznam o údržbe | text + od–do | — | — | Zobrazí sa všetkým ako banner. | G |
| Verzia | read-only version + odkaz na zoznam zmien | — | — | — | — |

---------------------------------------------------------------------------------------------------
## M9 Nastavenia na mobile
List of sections → full-screen section pages. Available on mobile: 01a Vzhľad + Klasické zobrazenie, 01d Oneskorenie
odoslania, 03b Môj profil, 04 Odpovede (čítanie a použitie), 06 Mimo kancelárie, 07 AI asistent (zapnutie, zhrnutia,
ranný prehľad), 08 Notifikácie, 09 Bezpečnosť (relácie, zariadenia). Other sections show "Toto nastavenie upravíte na
počítači." Saving on mobile always explicit (`Uložiť` in the app bar) to avoid accidental changes.

---------------------------------------------------------------------------------------------------
## Acceptance
- Every field in this file exists with the given control, default, validation and help text (snapshot of
  `settings_schema.json` generated from code compared with this spec in CI).
- Search finds every field by its label and at least one synonym.
- Changing a user-section field never requires a page reload and survives logout/login (per person).
- Admin changes are in the audit log with before/after; ⚠ actions require confirmation (and re-auth > 15 min).
- Figma: one frame per section (`W12-01 … W12-20`) incl. sub-frames listed above, each with default + error + saved
  state; M9 list + 3 example section pages.
