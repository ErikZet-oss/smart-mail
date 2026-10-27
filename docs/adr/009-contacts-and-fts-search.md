# ADR-009: Local contacts and Postgres FTS search (Phase 1g)

- Status: accepted (Phase 1g-a backend)
- Context: Roundcube parity needs a local address book (personal + shared) with vCard import/export, and folder
  search with scope/fields. Money and AI search are later phases. IMAP must stay read-only for contacts.

## Decision
1. **Contacts** are stored only in PostgreSQL (`address_books`, `contacts`, emails/phones, groups). Personal books
   belong to a person; shared books are company-wide. Never APPEND/STORE contacts on the IMAP server.
2. **vCard** 3.0 import/export (including Roundcube export shape); duplicates matched by e-mail with
   `merge` or `skip`; invalid files → 422. Fixtures use `@smartmail.test` only.
3. **Search** uses `tsvector` built with `to_tsvector('simple', unaccent(...))` and
   `plainto_tsquery('simple', unaccent(...))` so diacritics match both ways. Field filters restrict which
   columns contribute; scope = current folder / subfolders / all accessible folders.
4. **ACL**: results only from mailboxes with `mailbox_access` for the account. Folders with `private=true` and
   `owner_person_id` ≠ active person are excluded.
5. **W11**: UI ships a Phase-1 subset only (see `docs/plans/phase-1.md`); Firmy/Doklady/Asistent groups are absent
   until phases 3 and 5.

## Consequences
- GIN index on `messages.search_vector`; trigger keeps it updated when subject/addresses/body change.
- Autocomplete for compose reads local contacts (and optionally recent local recipients), never Money in 1g.
