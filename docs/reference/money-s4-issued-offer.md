<!--
Reference only (added 26 October 2026, DECISIONS D28). Written for the customer's separate "money-cloud" sync project,
not for Smart Mail. Useful for Phase 6 (offers): IssuedOffer fields, query/mutation shapes, introspection queries.
NOT applicable to Smart Mail: the SQL path (section 6: direct SELECT/UPDATE on the Money database), the Render cloud
endpoints (section 7) and the Windows sync tasks (section 8). Smart Mail talks to Money only through the bridge and the
official API (REST/GraphQL) and never writes to the Money SQL database (D28). Fields marked "overiť" must be verified by
introspection of the customer's server before use — never guessed (CLAUDE.md §7). GraphQL examples are fenced as
`text` on purpose: they target the official S5API schema, not the customer's server, so the schema drift check
(tools/validate_graphql.py) must not validate them.
-->

# Money S4 – Ponuky vystavené (IssuedOffer): API dokumentácia

Dokument popisuje, ako sa dá v Money S4/S5 pracovať s agendou **Ponuky vystavené**
(česky *Nabídky vydané*, v API `IssuedOffer`) a ako to robí naša appka (sync agent
`sync_agent/sync_money.py` + cloud na Renderi).

> **Najdôležitejšie na úvod:** na našom serveri (Money S4, agenda `S4_Agenda_SMARTSro`)
> REST ani GraphQL API ponuky vystavené **nevracia**. Sync agent ich preto číta priamo
> z SQL databázy Money. Oficiálna schéma S5API ponuky obsahuje (kapitola 3), takže
> po aktualizácii Money / povolení agendy v nastavení API by sa dali čítať aj cez GraphQL.

---



## 1. Prehľad prístupových ciest


| Cesta                                                      | Stav u nás                                              | Čítanie            | Zápis                                                       |
| ---------------------------------------------------------- | ------------------------------------------------------- | ------------------ | ----------------------------------------------------------- |
| REST `/v1.0/IssuedOffer`                                   | neexistuje (404)                                        | –                  | –                                                           |
| GraphQL `POST /graphql` – `IssuedOffer`, `IssuedOfferList` | na našom serveri nedostupné, v oficiálnej S5 schéme áno | áno (podľa schémy) | `CreateIssuedOffer`, `EditIssuedOffer`, `DeleteIssuedOffer` |
| SQL Server `dbo.Objednavky_NabidkaVydana`                  | **používa sa**                                          | áno                | len `Poznamka` (UPDATE)                                     |


---



## 2. Pripojenie a autentifikácia (REST + GraphQL)

API sa zapína v Money: **Administrácia → Výmena dát → REST API** (konfigurácia API,
vygenerovanie *Client ID* a *Client Secret*, výber sprístupnených agend). S5API je
samostatne licencovaný modul.

### 2.1 Premenné prostredia agenta


| Premenná              | Predvolená hodnota                         | Význam                                 |
| --------------------- | ------------------------------------------ | -------------------------------------- |
| `MONEY_URL`           | `http://localhost:81`                      | adresa Money API servera               |
| `MONEY_CLIENT_ID`     | (v `sync_secrets.env`)                     | Client ID z konfigurácie API           |
| `MONEY_CLIENT_SECRET` | (v `sync_secrets.env`)                     | Client Secret                          |
| `MONEY_SQL_SERVER`    | `SMARTSERVER`                              | SQL Server s databázou Money           |
| `MONEY_SQL_DATABASE`  | `S4_Agenda_SMARTSro`                       | databáza agendy                        |
| `RENDER_URL`          | `https://money-cloud-backend.onrender.com` | cloud                                  |
| `SYNC_API_KEY`        | (v `sync_secrets.env`)                     | Bearer kľúč pre `/api/sync-*` v cloude |


Tajné hodnoty patria len do `sync_secrets.env` na Windows serveri a do Render env, nie do gitu.

### 2.2 Získanie tokenu (OAuth2 client_credentials)

```http
POST {MONEY_URL}/connect/token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&client_id=<CLIENT_ID>&client_secret=<CLIENT_SECRET>
```

Odpoveď:

```json
{ "access_token": "eyJ...", "expires_in": 3600, "token_type": "Bearer" }
```

Každá ďalšia požiadavka posiela hlavičku `Authorization: Bearer <access_token>`.

Ako to robí agent (`MoneyClient`):

- token obnovuje každých 45 minút (`TOKEN_REFRESH_SEC`);
- pri `401` zahodí token a skúsi znova;
- pri `429/500/502/503/504` skúša až 3× s čakaním 2 s, 4 s;
- timeout spojenia 10 s, čítania 60 s.



### 2.3 Príklad v curl

```bash
TOKEN=$(curl -s -X POST "$MONEY_URL/connect/token" \
  -d grant_type=client_credentials \
  -d client_id="$MONEY_CLIENT_ID" \
  -d client_secret="$MONEY_CLIENT_SECRET" | jq -r .access_token)

curl -s -X POST "$MONEY_URL/graphql" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"query":"query($id: ID!){ IssuedOffer(ID:$id){ ID CisloDokladu } }","variables":{"id":"<GUID>"}}'
```

---



## 3. GraphQL API (oficiálna schéma S5API)

Endpoint: `POST {MONEY_URL}/graphql`, telo `{"query": "...", "variables": {...}}`.
Zdroj: oficiálna dokumentácia S5ApiQuery / S5ApiMutation (GraphQLDocOff).

### 3.1 Query

```text
# Nabídka vydaná – jeden doklad
IssuedOffer(ID: ID!): IssuedOffer

# Nabídka vydaná (seznam)
IssuedOfferList(
  Filter: String,
  From: Int,          # offset (0, 200, 400, ...)
  Count: Int,         # veľkosť strany
  ChangeFrom: DateTime  # len doklady zmenené od tohto času
): [IssuedOffer]

# Položka nabídky vydané – jedna položka
IssuedOfferItem(ID: ID!): IssuedOfferItem

# Položka nabídky vydané (seznam)
IssuedOfferItemList(
  Filter: String,
  From: Int,
  Count: Int,
  ChangeFrom: DateTime
): [IssuedOfferItem]
```

> **Pozor na názvy zoznamov na S4:** náš server pri iných agendách používa množné
> číslo namiesto `...List` (napr. `IssuedSalesDocs`, `IssuedDeliveryNotes`). Ak by sa
> ponuky na serveri sprístupnili, zoznam sa môže volať `IssuedOffers` namiesto
> `IssuedOfferList`. Overíte to introspekciou (3.5).

`Filter` je textový reťazec v syntaxe Money API (napr. `CisloDokladu~eq~NV0001`).
Syntax je potrebné overiť priamo na serveri, náš agent `Filter` nepoužíva –
inkrement rieši cez `ChangeFrom`.

### 3.2 Príklad – stránkovaný zoznam

Rovnaký vzor agent používa pre predajky a dodacie listy (`list_gql_ids`):

```text
query($from: Int, $count: Int, $changed: DateTime) {
  IssuedOfferList(From: $from, Count: $count, ChangeFrom: $changed) {
    ID
    CisloDokladu
    DatumVystaveni
    PlatnostDo
    SumaCelkem
    PriznakVyrizeno
    Modify_Date
  }
}
```

```json
{ "from": 0, "count": 200, "changed": "2026-10-23T00:00:00" }
```

Stránkovanie: zvyšujte `from` o počet vrátených riadkov, kým nepríde prázdne pole.
Agent má poistku 10 000 záznamov pri inkremente a 500 000 pri plnom importe.

### 3.3 Príklad – detail s položkami

```text
query($id: ID!) {
  IssuedOffer(ID: $id) {
    ID
    CisloDokladu
    Nazev
    DatumVystaveni
    PlatnostOd
    PlatnostDo
    DatumVyrizeni
    PriznakVyrizeno
    Schvaleno
    Stav
    SumaZaklad
    SumaDan
    SumaCelkem
    ZiskZaDoklad
    ProcentniZisk
    InterniPoznamka
    Firma { ID Nazev }
    Polozky {
      ID
      CisloPolozky
      Nazev
      Katalog
      Mnozstvi
      Jednotka
      JednCena
      CelkovaCena
      DphSazba
      DphZaklad
      DphDan
      Poznamka
      Stredisko_ID
    }
  }
}
```



### 3.4 Mutácie

```text
# Nabídka vydaná (zápis)
CreateIssuedOffer(IssuedOffer: IssuedOfferInput!): IssuedOffer

# Nabídka vydaná (editace)
EditIssuedOffer(IssuedOffer: IssuedOfferInput!): IssuedOffer

# Nabídka vydaná (mazání)
DeleteIssuedOffer(ID: ID!): ID
```

Pri `EditIssuedOffer` sa v `IssuedOfferInput` posiela `ID` existujúceho dokladu
a len polia, ktoré sa menia. Položky sa posielajú v `Polozky: [IssuedOfferItemInput]`.

Príklad – zmena poznámky (náhrada nášho SQL UPDATE, ak by API ponuky podporovalo):

```text
mutation($o: IssuedOfferInput!) {
  EditIssuedOffer(IssuedOffer: $o) { ID CisloDokladu Poznamka }
}
```

```json
{ "o": { "ID": "<GUID ponuky>", "Poznamka": "riadok 1\r\nriadok 2" } }
```

Príklad – vytvorenie ponuky:

```text
mutation($o: IssuedOfferInput!) {
  CreateIssuedOffer(IssuedOffer: $o) { ID CisloDokladu }
}
```

```json
{
  "o": {
    "Nazev": "Ponuka – zákazník XY",
    "DatumVystaveni": "2026-10-23",
    "PlatnostDo": "2026-11-22",
    "Firma_ID": "<GUID firmy>",
    "Polozky": [
      { "Nazev": "Tovar A", "Mnozstvi": 2, "Jednotka": "ks", "JednCena": 10.5 }
    ]
  }
}
```

Presný zoznam vstupných polí (`Firma_ID` vs. `Firma`, `CiselnaRada_ID`, …) si overte
introspekciou typu `IssuedOfferInput`.

### 3.5 Overenie, čo server naozaj podporuje (introspekcia)

```text
{
  __schema { queryType { fields { name } } mutationType { fields { name } } }
}
```

a pre polia typu:

```text
{ __type(name: "IssuedOffer") { fields { name type { name kind ofType { name } } } } }
```

Ak v zozname chýba `IssuedOffer`, agenda nie je sprístupnená (licencia / nastavenie
REST API v Money / staršia verzia S4) – presne to je dnešný stav u nás.

---



## 4. Polia typu `IssuedOffer` (Nabídka vydaná)

Podľa oficiálnej schémy. Polia s `_ID` sú GUID odkazy, bez `_ID` vnorené objekty.

### 4.1 Systémové


| Pole                          | Význam                               |
| ----------------------------- | ------------------------------------ |
| `ID`                          | GUID dokladu                         |
| `Parent_ID`, `Root_ID`        | hierarchia objektu                   |
| `Group_ID`                    | skupina zoznamu (priečinok v agende) |
| `Hidden`, `Deleted`, `Locked` | príznaky skrytý / zmazaný / zamknutý |
| `Create_ID`, `Create_Date`    | kto a kedy vytvoril                  |
| `Modify_ID`, `Modify_Date`    | kto a kedy naposledy zmenil          |
| `Storno`                      | stornovaný doklad                    |




### 4.2 Hlavička dokladu


| Pole                                         | Význam                                                |
| -------------------------------------------- | ----------------------------------------------------- |
| `CisloDokladu`                               | číslo ponuky (napr. NV2600123)                        |
| `CiselnaRada`                                | číselný rad                                           |
| `Nazev`                                      | popis ponuky                                          |
| `DatumVystaveni`                             | dátum vystavenia                                      |
| `PlatnostOd`, `PlatnostDo`                   | platnosť ponuky                                       |
| `DatumVyrizeni`                              | dátum vybavenia                                       |
| `DatumSchvaleni`, `Schvaleno`, `Schvalil_ID` | schválenie                                            |
| `DatumZauctovani`                            | dátum zaúčtovania                                     |
| `Stav`                                       | stav dokladu                                          |
| `Faze`                                       | fáza (0 = koncept) – v SQL áno, v GraphQL overiť      |
| `PriznakVyrizeno`                            | vybavená áno/nie                                      |
| `Vystavil`                                   | kto vystavil                                          |
| `Obchodnik`, `Obchodnik_ID`                  | obchodník                                             |
| `InterniPoznamka`                            | interná poznámka                                      |
| `Poznamka`                                   | poznámka (sem naša appka zapisovala ceny dodávateľov) |
| `PevneCeny`                                  | pevné ceny                                            |
| `Sleva`                                      | zľava na doklad                                       |
| `ZpusobDopravy_ID`, `ZpusobPlatby_ID`        | doprava, platba                                       |
| `CelkovaHmotnost`                            | hmotnosť                                              |




### 4.3 Odberateľ a adresy


| Pole                                                                   | Význam                      |
| ---------------------------------------------------------------------- | --------------------------- |
| `Firma` (`Company`)                                                    | firma z adresára            |
| `Stat` (`Country`)                                                     | štát                        |
| `AdresaNazev`, `AdresaUlice`, `AdresaMisto`, `AdresaPSC`, `AdresaStat` | adresa na doklade (v SQL)   |
| `AdresaKontaktniOsobaNazev`, `AdresaKontaktniOsobaPrijmeni`            | kontaktná osoba             |
| `AdresaKoncovehoPrijemce*` (Email, Telefon, …)                         | koncový príjemca            |
| `DodaciAdresaFirma`, `FakturacniAdresaFirma`                           | dodacia / fakturačná adresa |
| `KonecnyPrijemce`, `PrijemceFaktury`                                   | príjemcovia                 |
| `IC`, `DIC`, `ICDPH`                                                   | IČO, DIČ, IČ DPH (v SQL)    |




### 4.4 Sumy a zisk


| Pole                                        | Význam                            |
| ------------------------------------------- | --------------------------------- |
| `SumaZaklad`, `SumaDan`, `SumaCelkem`       | základ, DPH, celkom (domáca mena) |
| `SumaZakladCM`, `SumaDanCM`, `SumaCelkemCM` | to isté v cudzej mene             |
| `Dph0Zaklad`, `Dph1Zaklad`, `Dph2Zaklad`    | základy podľa sadzieb             |
| `Dph0Dan`, `Dph2Dan` (a ďalšie)             | DPH podľa sadzieb                 |
| `CelkovaCastka`                             | celková čiastka (v SQL)           |
| `ZiskZaDoklad`, `ProcentniZisk`             | zisk v € a v %                    |




### 4.5 Položky


| Pole      | Význam                              |
| --------- | ----------------------------------- |
| `Polozky` | `[IssuedOfferItem]` – riadky ponuky |


---



## 5. Polia typu `IssuedOfferItem` (Položka nabídky vydané)


| Pole                                                           | Význam                                 |
| -------------------------------------------------------------- | -------------------------------------- |
| `ID`, `Parent_ID`                                              | GUID položky, GUID ponuky              |
| `CisloPolozky`, `Poradi`                                       | poradie riadku                         |
| `Nazev`                                                        | názov riadku                           |
| `Katalog`                                                      | katalógové číslo                       |
| `Poznamka`                                                     | poznámka riadku                        |
| `TypPolozky`, `TypObsahu`                                      | typ riadku (tovar / text / služba …)   |
| `ObsahPolozky` (`ContentOfItemWithArticle`), `ObsahPolozky_ID` | odkaz na artikl / zásobu               |
| `Mnozstvi`, `Jednotka`                                         | množstvo, merná jednotka               |
| `JednCena`, `JednCenaCM`                                       | jednotková cena (domáca / cudzia mena) |
| `CelkovaCena`                                                  | cena riadku                            |
| `VychoziJednotkovaCena`, `VychoziCelkovaCena`                  | pôvodné ceny pred zľavou               |
| `Sleva`                                                        | zľava riadku                           |
| `DphSazba`, `SazbaDPH_ID`                                      | sadzba DPH                             |
| `DphZaklad`, `DphDan`, `DphCelkem`                             | základ, DPH, s DPH                     |
| `Stredisko`, `Stredisko_ID`                                    | stredisko (pobočka)                    |
| `Zakazka_ID`                                                   | zákazka                                |
| `PriznakVyrizeno`, `Vyrizeno`, `MnozstviVyrizeno`              | vybavenie                              |
| `Zbyva`, `MnozstviZbyva`                                       | zostáva vybaviť                        |
| `JednotkovaHmotnost`, `CelkovaHmotnost`                        | hmotnosť                               |
| `ParentObject_ID`                                              | nadradený objekt                       |
| `AttachmentList`                                               | prílohy                                |


---



## 6. SQL cesta (to, čo appka reálne používa)

Pripojenie: `pyodbc`, `Trusted_Connection=yes` (Windows účet, pod ktorým beží úloha),
server `SMARTSERVER`, databáza `S4_Agenda_SMARTSro`. Ovládače sa skúšajú v poradí
ODBC Driver 18/17/13, SQL Server Native Client 11.0, SQL Server.

### 6.1 Tabuľky


| Tabuľka                               | Obsah                               |
| ------------------------------------- | ----------------------------------- |
| `dbo.Objednavky_NabidkaVydana`        | hlavičky ponúk vystavených          |
| `dbo.Objednavky_PolozkaNabidkyVydane` | položky (`Parent_ID` = `ID` ponuky) |


Názvy stĺpcov sú rovnaké ako polia v GraphQL schéme.

### 6.2 Zoznam ID (plný aj inkrementálny)

```sql
SELECT CAST(ID AS nvarchar(36)) AS ID
FROM dbo.Objednavky_NabidkaVydana
WHERE Deleted = 0
  -- len pri inkremente:
  AND (Modify_Date >= ? OR Create_Date >= ? OR DatumVystaveni >= ?)
ORDER BY DatumVystaveni, ID
```



### 6.3 Detail hlavičiek (dávky po 80 ID – `SQL_DETAIL_BATCH`)

```sql
SELECT ID, CisloDokladu, DatumVystaveni, DatumVyrizeni, PlatnostDo,
       CelkovaCastka, SumaCelkem, SumaZaklad, SumaDan,
       Dph0Zaklad, Dph1Zaklad, Dph2Zaklad, ZiskZaDoklad,
       PriznakVyrizeno, Faze, Schvaleno,
       AdresaNazev, IC, ICDPH, DIC, AdresaUlice, AdresaMisto, AdresaPSC, AdresaStat,
       AdresaKoncovehoPrijemceEmail, AdresaKoncovehoPrijemceTelefon,
       Stredisko_ID, Poznamka, Nazev, Modify_Date, Create_Date
       -- + stĺpec skupiny zoznamu, ak existuje (Skupina_ID / SkupinaSeznamu_ID / Group_ID / ...)
FROM dbo.Objednavky_NabidkaVydana
WHERE Deleted = 0 AND ID IN (?, ?, ...)
```

Úpravy po načítaní: hodnoty sa prevedú na JSON (dátumy ISO, Decimal → číslo, GUID → text),
`ID` sa zmení na malé písmená, `PlatnostDo` sa skopíruje do `DatumSplatnosti`.

### 6.4 Položky

```sql
SELECT ID, Parent_ID, Nazev, Poznamka, Mnozstvi, Jednotka, JednCena,
       CelkovaCena, DphZaklad, Katalog, Stredisko_ID, CisloPolozky
FROM dbo.Objednavky_PolozkaNabidkyVydane
WHERE Deleted = 0 AND Parent_ID IN (?, ?, ...)
ORDER BY CisloPolozky, ID
```

Položky sa vložia do hlavičky ako pole `Polozky`.

### 6.5 Doplnenie údajov

- **Stredisko** (`Stredisko_ID` → názov): REST `GET /v1.0/Centre/{id}`, záložne
`/v1.0/Stredisko/{id}` a `/v1.0/CostCentre/{id}`; zoznam `GET /v1.0/Centre?$top=100&$skip=N`.
REST API teda na serveri beží, len agendu ponúk nesprístupňuje.
- **Skupina zoznamu**: agent v SQL katalógu nájde FK stĺpec skupiny
(`Skupina_ID`, `SkupinaSeznamu_ID`, `Group_ID`, `Folder_ID`, …) a doplní názov skupiny.
V cloude sa podľa nej dá filtrovať (spolu s faktúrami a predajkami).



### 6.6 Zápis poznámky do Money

```sql
-- hlavička ponuky
UPDATE dbo.Objednavky_NabidkaVydana
SET Poznamka = ?
WHERE Deleted = 0 AND ID = CAST(? AS uniqueidentifier)

-- staršia varianta: poznámka riadku
UPDATE dbo.Objednavky_PolozkaNabidkyVydane
SET Poznamka = ?
WHERE Deleted = 0 AND ID = CAST(? AS uniqueidentifier)
```

Konce riadkov sa normalizujú na `\r\n`, inak ich Money v memo poli nezobrazí správne.
Zápis do SQL obchádza validácie Money, preto sa mení **len** textové pole `Poznamka`.

### 6.7 Stav vybavenia a koncepty

```sql
-- stav vybavenia (hodinovo posledných 62 dní, alebo celé backfill)
SELECT CAST(ID AS nvarchar(36)), CAST(PriznakVyrizeno AS int)
FROM dbo.Objednavky_NabidkaVydana
WHERE Deleted = 0
  AND DatumVystaveni >= DATEADD(day, -62, CAST(GETDATE() AS date))

-- koncepty
SELECT CAST(ID AS nvarchar(36)), CAST(Faze AS int), CAST(Schvaleno AS int)
FROM dbo.Objednavky_NabidkaVydana
WHERE Deleted = 0 AND Faze = 0
```


| Pole              | Hodnoty                         | Ako to berie appka                                       |
| ----------------- | ------------------------------- | -------------------------------------------------------- |
| `PriznakVyrizeno` | 0/1                             | 1 = vybavená ponuka                                      |
| `Faze`            | 0 = koncept, inak riadny doklad | koncepty sú v cloude kurzívou a nerátajú sa do štatistík |
| `Schvaleno`       | 0/1                             | schválená ponuka                                         |


---



## 7. Mapovanie do cloudu

Agent posiela každú ponuku `POST {RENDER_URL}/api/sync-invoice` (Bearer `SYNC_API_KEY`)
do tabuľky `invoices` s `document_type = "IssuedOffer"`:


| Pole v cloude     | Zdroj v Money                                                                                      |
| ----------------- | -------------------------------------------------------------------------------------------------- |
| `id`              | `ID`                                                                                               |
| `document_number` | `CisloDokladu`                                                                                     |
| `total_price`     | `CelkovaCastka`, inak `SumaCelkem`                                                                 |
| `issue_date`      | `DatumVystaveni`                                                                                   |
| `due_date`        | `DatumSplatnosti` (= `PlatnostDo`), inak `DatumVyrizeni`                                           |
| `variable_symbol` | `VariabilniSymbol`, inak `CisloDokladu`                                                            |
| `customer_name`   | `AdresaNazev`                                                                                      |
| `document_type`   | `IssuedOffer`                                                                                      |
| `raw_data`        | celý JSON hlavičky + `Polozky` + `_Agenda`; `PriznakVyrizeno`/`Schvaleno` ako bool, `Faze` ako int |


Testovacie doklady (podľa čísla/odberateľa) sa neposielajú.

Ďalšie cloud endpointy pre ponuky (všetky Bearer `SYNC_API_KEY`):


| Endpoint                               | Smer          | Obsah                                                           |
| -------------------------------------- | ------------- | --------------------------------------------------------------- |
| `POST /api/sync-invoice`               | agent → cloud | jedna ponuka                                                    |
| `POST /api/sync-offer-status-batch`    | agent → cloud | `[{"id", "priznak_vyrizeno"}]`, dávky po 200                    |
| `POST /api/sync-phase-batch`           | agent → cloud | `[{"id", "faze", "schvaleno"}]`, dávky po 200                   |
| `GET /api/sync-offer-note-write-queue` | cloud → agent | `{"items": [{"offer_id", "poznamka", "document_number", ...}]}` |


---



## 8. Spúšťanie (Windows server)


| Príkaz                                            | Čo robí                                                                                                                              |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| hodinová úloha (bez prepínačov)                   | inkrement všetkých agend vrátane ponúk (dnešné + 2 h cez polnoc) + stav vybavenia za 62 dní                                          |
| `python sync_money.py --full --types IssuedOffer` | plný import všetkých nezmazaných ponúk zo SQL                                                                                        |
| `python sync_money.py --offer-status`             | backfill `PriznakVyrizeno` všetkých ponúk                                                                                            |
| `python sync_money.py --offer-notes-pulse`        | rýchla vetva: ponuky za posledných 20 min + zápis poznámok z fronty (úloha `MoneyCloudOfferNotesPulse`, `run_offer_notes_pulse.bat`) |
| `python sync_money.py --offer-note-write-queue`   | len vyprázdni frontu poznámok do Money                                                                                               |


Každá agenda má vlastný zámok (`sync-IssuedOffer.lock`); ak beží, hodinový sync ju preskočí.

---



## 9. Zápis cien dodávateľov do ponúk (vypnuté)

Cloud po synchronizácii ponuky vedel vyhľadať ceny/sklad u dodávateľov a zaradiť text
do fronty `/api/sync-offer-note-write-queue`, ktorú agent zapísal do `Poznamka` (6.6).

Stav: **vypnuté v kóde** (`supplier_shops/offer_supplier_notes.py`). Zapne sa len
premennou `OFFER_SUPPLIER_NOTES=on` v Render **a** prepínačom v Nastaveniach. Kým je
vypnuté, endpoint fronty vracia prázdny zoznam, takže agent do Money nič nezapíše.

---



## 10. Známe obmedzenia a odporúčania

1. **REST/GraphQL bez ponúk** – na našom S4 serveri. Pred prechodom na API overte
  introspekciou (3.5), či sa `IssuedOffer` po aktualizácii Money / povolení agendy objavil.
2. **SQL zápis** obchádza biznis logiku Money – používať len pre textové polia (`Poznamka`),
  nikdy pre sumy, položky či stavy. Na tie je určená mutácia `EditIssuedOffer`.
3. **Zmazané doklady** sa filtrujú `Deleted = 0`; do cloudu sa zmazanie samo nepropaguje.
4. **Časy** v Money SQL sú lokálny čas servera (Europe/Bratislava), bez časovej zóny.
5. Polia označené „v SQL“ (`CelkovaCastka`, `AdresaNazev`, `IC`, `Faze`, …) sú overené na
  našej databáze; v GraphQL sa môžu volať inak – overiť cez `__type(name: "IssuedOffer")`.

