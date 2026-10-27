# Phase 1 plan — mail client with Roundcube parity (proposed 26 October 2026, awaiting customer approval)

Scope and acceptance: CLAUDE.md §12 Phase 1. Screens: `docs/FIGMA_MAP.md`. Work in 8 milestones; after each one:
all CI gates green, push, Playwright screenshots next to the Figma frames sent to the customer for review.

| # | Milestone | Screens | Content |
|---|---|---|---|
| 1a | Foundation & login | W1, W1a, W1c, W16, W17 | mailbox login via IMAP (like Roundcube), "Zostať prihlásený", logout on password change, login rate limit, server-side sessions + CSRF, error pages; data model: accounts, sessions, persons, branches, audit_log |
| 1b | Branches & "Kto ste?" | W1b, W2b, M0 | person picker after branch-mailbox login, PersonChip switching, device remembers last person, person_id + account_id in every audit entry |
| 1c | Shell & folders | G1–G7, W2 folder column | rail, folders with SK SPECIAL-USE names and counts, customer folders (D21), quota %, sync (IDLE on INBOX, 2-min poll of other subscribed folders) |
| 1d | List & reading | W2, W2a, W2c, W2e, W2i–W2o | Zoznam/Konverzácie, density, Nastavenia zoznamu, sanitized HTML, blocked remote images, attachments, Roundcube toolbar order, Označiť/Viac, bulk actions, print, source, Klasické zobrazenie, dark mode |
| 1e | Compose | W4, W4b–f | reply/forward/new, identities, branch signature with the active person, Odpovede, attachments, drafts autosave 30 s, undo send 10 s, priority, delivery receipt |
| 1f | Settings | W12-01…06, 09, 09b, 10–12 | Roundcube order; Filtre + Mimo kancelárie via ManageSieve; HTML signature editor with source code + images (D22); branches & persons, users & roles, mailboxes |
| 1g | Contacts & search | W9, W10, W11 | address book, vCard import, search scope + fields; **W11 basic palette only** (see note) |
| 1h | Mobile & finish | M0–M4, M8, M9, M15, M18, W13–W15b | PWA, mobile screens, onboarding tour, shortcuts, O systéme, `tools/roundcube_import.py`, axe a11y |

**W11 (1g) vs CLAUDE.md Phase 5:** CLAUDE.md lists the full command palette in Phase 5; this plan puts a
**basic** W11 in 1g. Groups shown: Príkazy of Phase 1 only (Vytvoriť správu, Prejsť na priečinok, Prepnúť osobu,
Nastavenia), E-maily, Kontakty. Groups **Firmy**, **Doklady** and **Asistent** are not rendered at all (not disabled
buttons) — they arrive in Phase 3 (Firmy/Doklady) and Phase 5 (Asistent / full palette).

**Search coverage (1g-b UI):** backend search only covers messages already downloaded into Postgres (not live IMAP).
When the corpus is incomplete, W10 must show „Hľadá sa v správach od …“ (see README / ADR-009).

Guards: no real e-mail during development (test IMAP server + Mailpit), no Money, no AI in Phase 1.

Needed from the customer (not blocking 1a–1b): a test mailbox on mail2.nameserver.sk (credentials only in `.env`,
never in chat or git) before 1c; ManageSieve availability (port 4190) checked with that mailbox; pilot hosting
decided before 1h.
