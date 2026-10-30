# ADR-015: Prehlásenie o zhode (atest 2.1)

Status: accepted (Erik, 2026-10-30, issue #139)

## Context
Customers ask for „atest 2.1“, the supplier's declaration of conformity. Smart Mail should fill it in, add the branch
stamp and the manager's signature, and attach it to the draft reply. The look is Erik's approved template
(`design/reference/prehlasenie_o_zhode/`).

## Decisions
1. **Numbering:** one series for the whole company, `PZ-RRRR-NNNN`. It restarts each year, has no gaps and never
   repeats. The counter is a row in `org_settings` (`conformity.counter`) locked with `SELECT … FOR UPDATE` inside the
   issue transaction, so no extra sequence table.
2. **Header from the branch** (`branches` name, address, phone); **footer** = company seat (Novozámocká 232,
   949 01 Nitra, IČ DPH SK2020393606, web); IČO from `org_settings` (empty = left out).
3. **„Vystavil“ = the branch manager** (`persons.is_manager`): name, function and signature, even when another
   salesperson prepares it. The person who really issued it is stored (`prepared_by_person_id`) and audited. If the branch
   has no manager with a signature, issuing is blocked (`no_manager_signature`); no branch stamp → `no_branch_stamp`.
4. **Data model** (approved): `branches.stamp_key`, `persons.signature_key`, table `conformity_declarations`
   (migration 0017). An issued declaration is never edited; a correction gets a new number.
5. **Images:** transparent PNG, max 1 MB, uploaded only by an admin with a re-auth (audited). They are never served
   publicly or used as e-mail signature variables — only the server-side PDF render and an admin preview read them.
6. **Render:** Jinja2 + WeasyPrint like the other print documents (DOCUMENTS_SPEC §4), not Playwright (no new
   dependency in the image). Font: Liberation Sans, already in the image (the template asks for Inter, which is not).
7. **AI** may propose a `conformity_declaration` suggestion (customer, document, products from the mail), but it never
   issues one; „Vystaviť“ is always a person's click (autonomy level 2).

## Delivery
Part A: data model + Pečiatka/Podpis in Settings 11. Part B: template, numbering, issue dialog, attachment to the draft.
Part C: the AI suggestion.
