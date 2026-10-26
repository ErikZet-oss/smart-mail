# Smart Mail – balík zadaní pre Claude Code, Cursor a Figmu

Tento balík obsahuje kompletné zadanie AI e-mailového klienta pre Smart s.r.o. (náhrada Roundcube, prepojenie
s Money S4 cez API modul – GraphQL podľa schémy vášho servera, REST na PDF, osoby a aktivity).

## Čo je v balíku
| Súbor | Na čo slúži | Kto ho číta |
|---|---|---|
| `CLAUDE.md` | hlavné zadanie: pravidlá, technológie, štruktúra, fázy s kritériami prevzatia | Claude Code / Cursor |
| `docs/DECISIONS.md` | **vaše rozhodnutia (v2.10, D1–D24)** – majú prednosť pred všetkým ostatným: len dodací list prijatý (bez faktúr prijatých), objednávky bez riešenia skladu, nikde zaokrúhľovanie na balenie, ponuky číslované v Money, všetky sklady a cenníky zo zoznamov Money, čas príjmu = čas zápisu, poplatky a vratky len v Money, nové logo, vzhľad podľa vášho Roundcube, bez PIN-u, práva AI si nastavuje každé prihlásenie | agent + vy |
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
| `.cursor/rules/smartmail.mdc` | pravidlo pre Cursor, ktoré ho nasmeruje na CLAUDE.md | Cursor |

## Postup krok za krokom
1. **Vytvorte prázdny repozitár** a nakopírujte doň celý balík. Schéma GraphQL (`graphql_schema.json`) a oba swaggery (`swagger_v1.json`, `swagger_v2.json`) sú už v `bridge/schema/` – needitujte ich.
2. **Claude Code**: v priečinku projektu spustite `claude` a napíšte: „Prečítaj CLAUDE.md a sprav Phase 0.“
   Po každej fáze agent zastaví a čaká na vašu kontrolu, potom: „Pokračuj Phase 1.“
   **Cursor**: otvorte priečinok, pravidlo `.cursor/rules/smartmail.mdc` sa načíta samo; v Agent režime napíšte to isté.
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
   obrazovku a jej stavy. Agent ju číta cez Figma MCP server – pripojte ho raz v priečinku projektu:
   `claude mcp add --transport http figma https://mcp.figma.com/mcp`, potom v Claude Code `/mcp` → figma → prihlásiť
   sa do Figmy. (Cursor: Settings › MCP › pridať server s rovnakou adresou.) Overenie: „Zobraz mi obrazovku W1 z Figmy.“
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
