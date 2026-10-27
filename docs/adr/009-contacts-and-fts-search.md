# ADR-009: Local contacts and Postgres FTS search (Phase 1g)

- Status: accepted (Phase 1g-a backend)
- Context: Roundcube parity needs a local address book (personal + shared) with vCard import/export, and folder
  search with scope/fields. Money and AI search are later phases. IMAP must stay read-only for contacts.

## Decision
1. **Contacts** are stored only in PostgreSQL (`address_books`, `contacts`, emails/phones, groups). Personal books
   belong to a person; shared books are company-wide (exactly one row — partial unique index on `kind = 'shared'`;
   personal uniqueness is a partial unique index on `owner_person_id`). Never APPEND/STORE contacts on IMAP.
   Viewers may read shared (and personal) books; writes/import/delete return 403. Shared-book mutations are audited
   with `person_id`.
2. **vCard** 2.1/3.0 import/export (Roundcube export shape; 2.1 `ENCODING=QUOTED-PRINTABLE` + `CHARSET=` utf-8 /
   windows-1250). Duplicates matched by e-mail with `merge` or `skip`; invalid → 422; over 5 MB or 5 000 contacts →
   413 (Slovak message). Fixtures use `@smartmail.test` only.
3. **Search** (Roundcube-like):
   - Each query word is a **prefix** after unaccent: `to_tsquery('simple', 'word1:* & word2:*')` against the
     maintained `messages.search_vector` (never `to_tsvector` at query time).
   - Weights on the vector: subject **A**, Od/Komu/Kópia **B**, body **D**.
   - Od / Komu / Kópia also match as **address substrings**:
     `unaccent(lower(...)) LIKE '%…%'` with `%`/`_` escaped (so `firma.sk` finds `jan@firma.sk`).
   - Extension **`pg_trgm`** + `immutable_unaccent()` expression GIN indexes on from/to/cc text for those LIKEs.
   - Scope: current / subfolders (`startswith(..., autoescape=True)`) / all; ACL via `mailbox_access` and private
     folders (`owner_person_id`).
4. **Coverage**: search only sees messages already synced into Postgres (first sync downloads the mailbox history the
   sync job fetches). UI (1g-b) must show „Hľadá sa v správach od …“ when the corpus is incomplete — not built in 1g-a.
5. **W11**: UI ships a Phase-1 subset only (see `docs/plans/phase-1.md`); Firmy/Doklady/Asistent groups are absent
   until phases 3 and 5.

## Consequences
- GIN on `search_vector`; trigram GIN on address expressions; trigger keeps weights updated.
- Autocomplete for compose reads local contacts (and recent local recipients), never Money in 1g.
