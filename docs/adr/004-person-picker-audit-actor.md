# ADR-004: Person picker, device memory and the audit actor

- Status: accepted (Phase 1b, 26 October 2026)
- Context: PRODUCT_SPEC §2.0, CLAUDE.md §4/§9, SCREENS_SPEC W1b/M0, UX_SPEC W2b, DECISIONS D9. A branch mailbox
  (e.g. senica@smartsro.sk) is one login used by several people; every action must carry the person who did it.

## Decision
1. **Who may be picked**: active persons whose home branch is the mailbox's branch, plus active persons covering it
   through `person_branches`. Order: managers first, then first name / last name in the Slovak alphabet (ch after h,
   diacritics as separate letters: a ä b c č d …). A personal account picks only its own person.
2. **API**: `GET /api/auth/persons` (list, `current_person_id`, `last_person_id` of this device, branch
   `idle_ask_minutes`) and `POST /api/auth/person {person_id, remember_device}`: one click, no PIN (D9), the session
   cookie stays the same. Audit `auth.person_selected` (first pick) or `auth.person_switched` (with `from_person_id`).
3. **Device memory** = table `device_person_memory (device_id, account_id) → last_person_id` (CLAUDE.md §4, migration
   `0004`), keyed by the long-lived `sm_device` cookie. The picker still shows on the next login, with that person
   preselected (Enter continues). M0 "Zapamätať na tomto telefóne" off = the row is deleted. Two devices may work as
   the same person at the same time.
4. **Deactivated / moved person**: every authenticated request re-checks the active person; if it is inactive or no
   longer belongs to the branch, the session's person is cleared, `auth.person_unavailable` is audited and the API
   answers `409 {code: person_inactive}` → the web opens W1b.
5. **No person = read-only**: the dependency `ActivePerson` answers `403 person_required` (no person; the web opens
   W1b) or `403 read_only` (viewer role) for every action that sends, assigns or approves (used from 1c on).
6. **Audit actor**: authentication stores (account_id, person_id) in a request-scoped context variable (reset by the
   middleware for every request); `audit()` fills both columns from it, so no entry of a signed-in request can miss
   the person.
7. **Idle re-ask** (branch setting, optional): after `idle_ask_minutes` without input the web shows W1b with the
   current person preselected. Measured in the browser; the server session timeout (12 h) is unchanged.

## Consequences
- Avatar colours come from a stable hash (FNV-1a) of the person id into five token colours, so a person keeps the
  colour on every screen and when the list changes; the Figma colours of the sample people are examples only. A photo
  replaces the colour when Settings 11 gets person photos.
- The PersonChip popover holds only the people in 1b; Môj profil, Klasické zobrazenie and Klávesové skratky are added
  with their screens (1c/1g/1h). Until the G1 rail exists (1c) the chip sits in a 72 px strip on the temporary page.
