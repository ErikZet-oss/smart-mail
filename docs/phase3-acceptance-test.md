# Fáza 3 – akceptačný test na TEST agende (checklist pre Erika)

Kritériá: CLAUDE.md §12, fáza 3. Agenda: **TEST** (13a ukazuje štítok TEST). Most beží na Windows serveri a test server
má `FEATURE_MONEY=true`. **Zápisy do Money ostávajú vypnuté** (13a „Zápisy do Money povolené“ = vypnuté), aktivity (13d)
sa nezapisujú. Test nič nezapisuje do Money a e-maily idú len na vaše vlastné testovacie schránky.

Výsledok si zapíšte priamo sem (☐ → ☑) alebo do komentára v #176.

## 0. Príprava (raz)
- ☐ 13a: stav „Pripojené“, verzia API 1.15.11, posledná synchronizácia bez chýb (firmy, osoby, číselníky).
- ☐ 13b: vyplnená firemná tlačová zostava SK. „Vyskúšať PDF“ otvorí PDF faktúry. Zostavy pre pobočky pribudnú s #174.
- ☐ Pripravte si **3 testovacie e-mailové adresy mimo firmy** (napr. súkromné). Každú v Money **na TEST agende** priraďte
  k inej firme ako e-mail firmy alebo kontaktnej osoby. Označme ich A (firma A), B (firma B), C (firma C).
- ☐ Pre každú firmu si zapíšte 3–4 čísla jej vydaných faktúr (spolu aspoň 10).

## 1. 10 žiadostí o faktúru end-to-end
Pre každú z 10 faktúr pošlite z adresy firmy do testovacej schránky Smart Mail e-mail „Prosím o kópiu faktúry č. …“.
Striedajte formulácie: číslo faktúry, variabilný symbol, „faktúra z minulého týždňa“.

| # | Odosielateľ | Faktúra | Návrh správnej faktúry | Pripojené originálne PDF z Money | Odoslané len odosielateľovi | Poznámka |
|---|---|---|---|---|---|---|
| 1 | A | | ☐ | ☐ | ☐ | |
| 2 | A | | ☐ | ☐ | ☐ | |
| 3 | A | | ☐ | ☐ | ☐ | |
| 4 | B | | ☐ | ☐ | ☐ | |
| 5 | B | | ☐ | ☐ | ☐ | |
| 6 | B | | ☐ | ☐ | ☐ | |
| 7 | C | | ☐ | ☐ | ☐ | |
| 8 | C | | ☐ | ☐ | ☐ | |
| 9 | C | | ☐ | ☐ | ☐ | |
| 10 | C | | ☐ | ☐ | ☐ | |

Pri každej žiadosti skontrolujte:
- ☐ V paneli Zákazník je správna firma (pri zhode podľa domény sa Smart Mail najprv pýta).
- ☐ PDF je originál z Money (rovnaký ako tlač z Money), nie dokument vytvorený v Smart Mail.
- ☐ Po odoslaní je v Odoslaných správa s prílohou a s podpisom osoby, ktorá ju schválila.

## 2. 0 odoslaní nesprávnemu príjemcovi (negatívne testy — každý MUSÍ byť zablokovaný)
- ☐ Z adresy A požiadajte o faktúru firmy B → návrh nesmie ponúknuť faktúru B (žiadny návrh alebo „faktúra patrí inej
  firme“).
- ☐ V návrhu pre A pridajte pred odoslaním do Kópie adresu B → „Odoslať“ je zablokované (faktúra nepatrí príjemcovi).
- ☐ V návrhu pre A zmeňte Komu na adresu C → zablokované pri schválení aj pri odoslaní.
- ☐ Z neznámej adresy (nie je v Money) požiadajte o faktúru → žiadna príloha bez potvrdenia firmy.

Výsledok: **počet odoslaní nesprávnemu príjemcovi = ____ (musí byť 0)**.

## 3. Money offline nezastaví poštu
Na serveri pri Money zastavte službu mosta (`nssm stop SmartMailBridge`) alebo Cloudflare Tunnel, približne na 5 minút.
- ☐ Poštu je možné čítať, písať a odosielať (pošlite si 1 interný a 1 externý e-mail bez faktúry).
- ☐ Panel Zákazník, W8b, W9a a 13a ukazujú „Money nedostupné“, nič nezamrzne a nečaká sa dlhšie ako pár sekúnd.
- ☐ Žiadosť o faktúru prijatá počas výpadku → návrh bez prílohy alebo s upozornením, nikdy s nesprávnou faktúrou.
- ☐ Po zapnutí mosta (`nssm start SmartMailBridge`) sa do 2 minút stav vráti na „Pripojené“ a synchronizácia pokračuje.

## 4. Ďalšie obrazovky (rýchla kontrola)
- ☐ W8b Upomienky: dlžníci s faktúrami po splatnosti zodpovedajú Money (2–3 firmy porovnať so saldom v Money).
- ☐ W9a Zákazník 360: faktúry, objednávky a dodacie listy firmy zodpovedajú Money. Záložka Aktivity zatiaľ ukazuje
  „čaká na overenie“ (REST filtre nefungujú, #176).
- ☐ Globálne hľadanie / Ctrl+K: vyhľadanie firmy podľa IČO a faktúry podľa čísla.

## Hotovo, keď
Všetky riadky v 1 sú ☑, v 2 je 0 odoslaní nesprávnemu príjemcovi a 3 prejde. Potom môžeme otvoriť otázku fázy 4
(Erik rozhodne). Zápis aktivít (3f) zapneme až po samostatnom teste zápisu na TEST agende.
