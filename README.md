# Smart Mail – balík zadaní pre Claude Code, Cursor a Figmu

Tento balík obsahuje kompletné zadanie AI e-mailového klienta pre Smart s.r.o. (náhrada Roundcube, prepojenie
s Money S4 cez API modul – GraphQL podľa schémy vášho servera, REST na PDF, osoby a aktivity).

## Čo je v balíku
| Súbor | Na čo slúži | Kto ho číta |
|---|---|---|
| `CLAUDE.md` | hlavné zadanie: pravidlá, technológie, štruktúra, fázy s kritériami prevzatia | Claude Code / Cursor |
| `docs/DECISIONS.md` | **vaše rozhodnutia (v2.12, D1–D28)** – majú prednosť pred všetkým ostatným: len dodací list prijatý (bez faktúr prijatých), objednávky bez riešenia skladu, nikde zaokrúhľovanie na balenie, ponuky číslované v Money, všetky sklady a cenníky zo zoznamov Money, čas príjmu = čas zápisu, poplatky a vratky len v Money, nové logo, vzhľad podľa vášho Roundcube, bez PIN-u, práva AI si nastavuje každé prihlásenie, kontá vznikajú pri prvom prihlásení, heslo k pošte uložené šifrovane | agent + vy |
| `docs/PRODUCT_SPEC.md` | všetky funkcie, zhoda s Roundcube, kompletné nastavenia, roly, migrácia | agent + vy |
| `docs/UX_SPEC.md` | dizajn systém (farby, písmo, komponenty), obrazovky web a mobil, skratky, texty | agent + Figma |
| `docs/SCREENS_SPEC.md` | mapa aplikácie a popis každej stránky, podstránky a dialógu (web aj mobil): účel, rozloženie, obsah, tlačidlá, stavy | agent + Figma |
| `docs/SETTINGS_SPEC.md` | všetky nastavenia pole po poli: ovládací prvok, predvolená hodnota, kontrola, pomocný text, kto mení | agent + Figma |
| `docs/AI_ASSISTANT.md` | ako AI pracuje: úrovne samostatnosti, nástroje, prompty, poistky | agent |
| `docs/ORDERS_SPEC.md` | objednávky od zákazníkov: rozpoznanie, vyťaženie, párovanie, ceny, kontrola, zápis do Money, potvrdenie, zmeny, pravidlá a testy | agent + vy |
| `docs/MONEY_API.md` | prepojenie s Money S4: GraphQL dopyty a zápisy, párovanie kódov dodávateľov, dodacie listy, postupy | agent + implementátor Money |
| `docs/DOCUMENTS_SPEC.md` | doklady ako v Money: dodací list prijatý (karta ako v Money, pole po poli), ponuka a potvrdenie objednávky (PDF ako tlačová zostava Money), faktúry len ako PDF z Money, číslovanie | agent + Figma + vy |
| `templates/print/`, `tools/render_print.py`, `fixtures/documents/` | hotová šablóna PDF ponuky/potvrdenia v rozložení Money + vzorové (vymyslené) doklady na testy | agent |
| `docs/FIGMA_MAP.md` | **mapa obrazoviek → rámce vo Figme** (odkazy na každú obrazovku a stav, komponenty, toky) | agent + dizajnér |
| `FIGMA.md` | **čo je pripravené na grafiku (§0)**, poradie práce, postup návrhu vo Figme + hotový prompt pre Figma Make / AI | dizajnér / Figma |
| `design/` | farby, písmo, rozmery ako súbor na import do Figmy (`tokens.json`) a do kódu (`tokens.css`), kontrola kontrastu (`CONTRAST.md`), logo SVG/PNG a ikony aplikácie (`brand/`), anonymizované snímky vášho Roundcube ako predloha (`reference/roundcube/`) | Figma + agent |
| `tools/money_probe.py` | bezpečný testovací skript (len čítanie; `--orders` pre objednávky, `--branches` pre pobočky a dodacie listy) na overenie API Money | vy (spustiť na serveri) |
| `tools/validate_graphql.py` | kontrola všetkých GraphQL dopytov voči schéme vášho Money (beží v CI, chráni pred chybami v názvoch polí) | agent / CI |
| `app/`, `bridge/`, `web/`, `migrations/`, `tests/` | kód aplikácie (od fázy 0), Money most, webová aplikácia, migrácie databázy, testy | agent |
| `docker-compose.yml`, `.env.example`, `Makefile`, `.github/workflows/ci.yml` | spustenie celej aplikácie, popis nastavení, bežné príkazy, automatické kontroly na GitHube | agent / správca |
| `.cursor/rules/smartmail.mdc` | pravidlo pre Cursor, ktoré ho nasmeruje na CLAUDE.md | Cursor |

## Postup krok za krokom
1. **Repozitár je pripravený** (tento): zadania v2.10 + fáza 0 (kostra aplikácie, testy, Docker, CI). Schéma GraphQL
   a oba swaggery sú v `bridge/schema/` – needitujte ich.
2. **Claude Code**: otvorte priečinok v Cursore (rozšírenie Claude Code) alebo v termináli spustite `claude` a napíšte:
   „Prečítaj CLAUDE.md a pokračuj Phase 1.“ Agent najprv navrhne plán, po vašom súhlase programuje a po fáze zastaví.
   **Cursor (vlastný agent)**: pravidlo `.cursor/rules/smartmail.mdc` sa načíta samo.
3. **Pred fázou 3 (Money)** spustite na serveri pri Money (proti TESTOVACEJ agende):
   `python tools/money_probe.py --env probe.env` (návod je v hlavičke skriptu). Výsledok `probe_output/report.md`
   dajte do repozitára – agent z neho zistí presnú syntax filtrov a kódy operácií.
   **Pred objednávkami (fáza 4)** spustite aj `python tools/money_probe.py --env probe.env --orders` (len čítanie).
   Zápisový test (`--orders --allow-write-test`) spúšťajte len na testovacej agende – vytvorí a hneď zmaže 1 skúšobnú
   objednávku a overí zľavy, rezerváciu a textové položky. Výsledok `probe_output/orders.md` dajte do repozitára.
   **Pred dodacími listami (fáza 4)** spustite `python tools/money_probe.py --env probe.env --branches` (len čítanie):
   vypíše strediská, sklady, cenníky a číselné rady pre rozbaľovacie zoznamy v Nastaveniach a z existujúcich dodacích
   listov zistí, či má každá pobočka vlastný rad a ktoré pole obsahuje „Doklad prijatý“. Výsledok `probe_output/branches.md`.
4. **Figma je hotová**: https://www.figma.com/design/vBDv8OCQTjxPBMzq6KBcHU. `docs/FIGMA_MAP.md` obsahuje odkaz na každú
   obrazovku a jej stavy. Figma MCP server je v repozitári už nastavený (`.mcp.json`) – pri prvom spustení Claude Code
   potvrďte server „figma“ a v `/mcp` sa prihláste do Figmy. (Cursor: Settings › MCP › server `https://mcp.figma.com/mcp`.)
   Overenie: „Zobraz mi obrazovku W1 z Figmy.“
5. **Implementátor Money**: pošlite mu otázky z `docs/MONEY_API.md` §9 a `docs/ORDERS_SPEC.md` §20 (ponuky v API,
   zápis kódov dodávateľov, ID tlačových zostáv, práva API roly, termín dodania, rezervácia, zľavy, stavy objednávok,
   PDF dodacích listov a objednávok cez API).

## Pobočky
Na pobočke sa prihlasuje ako dnes – pobočkovým e-mailom a heslom. Potom si každý klikne na svoje meno ("Kto ste?") a
podpis sa nastaví sám; prepnúť osobu sa dá jedným klikom vpravo hore. Podrobnosti: `docs/PRODUCT_SPEC.md` §2.0.
Každá pobočka má v Nastaveniach (Pobočky › Money) vybraté zo zoznamov načítaných z Money svoje stredisko, cenník, sklad
a prípadne vlastné číselné rady – doklady z pobočky sa zapíšu presne pod ne.

## Doklady ako v Money
Dodací list prijatý vyzerá v Smart Mail rovnako ako karta v Money (rovnaké polia, poradie, stĺpce), ponuka a
potvrdenie objednávky majú rovnaké PDF ako tlačová zostava Money. Faktúry vystavené Smart Mail nikdy nevytvára –
k e-mailu priloží vždy originálne PDF z Money. Podrobnosti: `docs/DOCUMENTS_SPEC.md`.

## Dôležité poistky
- AI nikdy sama neodošle e-mail mimo firmu ani nezapíše doklad do Money – vždy pripraví návrh na jedno kliknutie.
- Vývoj a testy len na testovacej agende Money; ostrú agendu agent nesmie volať bez vášho výslovného súhlasu.
- Nové zápisové funkcie (dodacie listy prijaté, objednávky) bežia najprv v tieňovom režime: návrhy sa porovnávajú s tým, čo
  ľudia urobili v Money ručne, a tlačidlo zápisu sa zapne až pri dohodnutej presnosti.
- Roundcube môže bežať súbežne počas pilotu – obe aplikácie pracujú s tou istou poštou na serveri.

## Vývoj (od fázy 0)
Potrebujete Docker Desktop. Bez ďalšieho nastavovania:

```bash
docker compose up -d --build      # celá aplikácia: http://localhost:8080
docker compose ps                 # stav služieb
docker compose down               # zastaviť
```

| Adresa | Čo tam je |
|---|---|
| http://localhost:8080 | webová aplikácia (od fázy 1a prihlásenie e-mailom a heslom k pošte) |
| http://localhost:8000/api/docs | API backendu |
| http://localhost:8100/healthz | Money most (vo fáze 0 len testovacie dáta, zápisy vypnuté) |
| http://localhost:8025 | Mailpit – testovacia pošta, nič neodíde von |
| http://localhost:8333 | úložisko príloh (S3) |

### Prihlásenie (fáza 1a)
Prihlasuje sa e-mailom a heslom k pošte – heslo overí IMAP server (ten istý ako pre Roundcube). Server nastavte v `.env`:
`IMAP_LOGIN_HOST` (mail2.nameserver.sk), `IMAP_LOGIN_PORT` (993), `IMAP_LOGIN_SECURITY` (`ssl`/`starttls`).

- **Nové kontá (D25):** kto má adresu v doméne z `INTERNAL_DOMAINS`, tomu sa konto založí pri prvom úspešnom
  prihlásení – len na čítanie (rola viewer), kým mu správca nepridelí rolu. Adresy v `ADMIN_EMAILS` dostanú pri
  založení rolu admin. Iné domény sa neprihlásia.
- **Ochrana prihlásenia (D26):** 5 zlých pokusov na konto za 5 minút, 30 z jednej IP adresy; IP adresy firmy
  v `LOGIN_IP_ALLOWLIST` majú len limit na konto.
- **Heslo k pošte (D27)** sa uloží šifrovane kľúčom `APP_ENCRYPTION_KEY` (len v `.env`) pre synchronizáciu pošty;
  po zmene hesla sa prepíše hneď pri ďalšom prihlásení.
- **„Požiadať správcu“** na stránke 403 pošle e-mail na `ADMIN_CONTACT_EMAIL`.

### Kto ste? (fáza 1b)
Po prihlásení do pobočkovej schránky (napr. senica@smartsro.sk) sa zobrazí výber osoby: jedno kliknutie na meno a
pracujete – bez PIN-u. Vedúci je prvý, ostatní abecedne; kto naposledy pracoval na tomto počítači, je predvolený
(stačí Enter). Osobu prepnete kedykoľvek vľavo dole (avatar s menom alebo `Ctrl+Shift+P`) bez odhlásenia. V audite
je pri každom zázname schránka aj osoba. Neaktívna osoba sa v zozname nezobrazí; ak ju správca deaktivuje počas práce,
aplikácia znova otvorí výber. Menu osoby vždy obsahuje **Môj profil** a **Odhlásiť** (aj pri jednej osobe).

Pobočkové schránky a ďalšie osoby zatiaľ založíte príkazom (neskôr v Nastaveniach › Pobočky a osoby):

```bash
docker compose exec app python -m app.cli add-account jana@smartsro.sk --first-name Jana --last-name Nová --role sales
docker compose exec app python -m app.cli add-account nitra@smartsro.sk --branch Nitra      # pobočková schránka
docker compose exec app python -m app.cli add-person Nitra --first-name Peter --last-name Novák
docker compose exec app python -m app.cli maintenance on --until 2026-11-01T08:00:00+01:00  # obrazovka Údržba
docker compose exec app python -m app.cli maintenance off
```

### Kontakty a hľadanie (fáza 1g — backend)
Lokálne adresáre Osobné / Zdieľané, skupiny, vCard import/export (`fixtures/contacts/`), autocomplete.
Hľadanie: Roundcube rozsah a polia, Postgres FTS (`simple` + `unaccent`, prefix `:*`) + substring adries
(`pg_trgm`). **Hľadá sa len v správach už stiahnutých do Postgres** (prvá synchronizácia stiahne históriu
schránky podľa sync jobu) — nie online cez IMAP. Obrazovky (1g-b) majú zobraziť „Hľadá sa v správach od …“.
W11 v 1g len základná paleta (Príkazy fázy 1, E-maily, Kontakty — bez Firiem/Dokladov/Asistenta).

### Nastavenia (fáza 1f)
Sekcie W12 v poradí Roundcube: Nastavenia (01a–e), Priečinky, Identity / Môj profil, Odpovede, Filtre,
Mimo kancelárie (ManageSieve), Nastavenia e-mail schránky (09b, D20), Bezpečnosť, a pre správcu Používatelia,
Pobočky a osoby (podpis D22), Schránky. Odosielanie mimo `APP_ENV=prod` ide len cez Mailpit a len na
`@smartmail.test` / `MAIL_SEND_TEST_ALLOWLIST` (ADR-008). W4e upraví podpis len pre aktuálnu správu.
Live schránky (eshop@, info@, pobočky) sa nepoužívajú; `REAL_IMAP_TEST_*` ostáva preskočené, kým zákazník
nedodá `test@smartsro.sk`.

### Písanie (fáza 1e)
Nová správa / Odpovedať / Poslať ďalej otvára W4 (`/compose`). Identita, podpis pobočky s aktívnou osobou,
Odpovede (W4d), prílohy na S3 (SeaweedFS v compose), koncepty s autosave 30 s, Odoslať s Undo 10 s
(`UNDO_SEND_SECONDS`), priorita a potvrdenie o prečítaní. Pred odoslaním bežia kontroly (W4b). Telá správ
sa ťahajú len cez `BODY.PEEK[]` (nikdy RFC822). `STORAGE_BACKEND=s3` je predvolené; `local` len pre unit testy.
ClamAV ostáva na 1h. Seed IMAP má ≥ 60 fiktívnych správ (dlhé predmety, prílohy, vlákna, neprečítané).

### Zoznam a čítanie (fáza 1d)
Stredný stĺpec je zoznam správ (Zoznam / Konverzácie, hustota, filtre, stránkovanie ako Roundcube) a vpravo náhľad
s panelom akcií (Vymazať, Nevyžiadané, Označiť, Viac → Tlač / Zdroj, Vybavené, Odložiť). Odpovedať / Poslať ďalej
otvárajú W4. HTML je sanitizované, vzdialené obrázky sú zablokované (tlačidlo Zobraziť obrázky). Tmavý režim
a Klasické zobrazenie sú v ľavom raili / menu osoby. Surové `.eml` a prílohy sú na S3 (ADR-007; ClamAV najneskôr
v 1h). IMAP integračný test 1d (zoznam, vlákno, telo, príloha) beží v CI proti `imap-test` spolu s 1c; nikdy proti
live schránkam.

### Priečinky a synchronizácia (fáza 1c)
Po prihlásení sa otvorí E-mail (ľavý stĺpec ako v Roundcube): Doručená pošta, Koncepty, Odoslané, Nevyžiadaná pošta,
Kôš a vlastné priečinky (Dodávatelia, Faktúry, Kurier, Nitra, Senica, Smart, Trenčín – D21). Dole je kvóta (červená
nad 90 %) a stav Money (zatiaľ vypnuté). Worker sleduje Doručenú poštu cez IDLE a ostatné priečinky obnovuje každých
2 minúty. Live schránky firmy (eshop@, info@, pobočky) sa vo vývoji **nikdy** nepoužívajú.

Lokálny testovací IMAP (Dovecot) je v compose ako `imap-test`:

```bash
docker compose up -d imap-test
make imap-seed                 # vymyslené správy; RESET=1 vymaže a naplní znova
# prihlásenie: pilot@smartmail.test / pilot-test-heslo  (kvóta ~40 %)
#              plna@smartmail.test  / plna-test-heslo   (kvóta ~93 %, červená)
```

Integrácia voči skutočnému serveru `mail2.nameserver.sk` beží len keď sú v `.env` vyplnené `REAL_IMAP_TEST_*`
(výhradne testovacia schránka, ktorú dodá zákazník pred 1f) – inak sa test preskočí. Heslo nikdy do gitu ani do
chatu.

Pre programátora (agenta): `make check` spustí to isté čo CI okrem Dockeru (ruff, mypy, pytest vrátane golden
testov tlačových dokladov, eslint, prettier, tsc, vitest). Golden testy potrebujú `poppler-utils` a písmo z
`templates/print/fonts/`. Nastavenia: `.env.example` (skopírovať do `.env`, nikdy necommitovať).
Testy prihlásenia potrebujú PostgreSQL a Redis (`docker compose up -d db redis`; databáza `smartmail_test`, adresy v
`TEST_DATABASE_URL` / `TEST_REDIS_URL`) – bez nich sa lokálne preskočia, v CI musia prejsť. IMAP integračné testy
v CI: `docker compose up -d imap-test && make imap-seed` a `TEST_IMAP_HOST=localhost TEST_IMAP_PORT=1143
REQUIRE_IMAP=1`. `make e2e` spustí Playwright (desktop + mobil, API simulované) a uloží snímky obrazoviek do
`web/test-results/screens/`.
