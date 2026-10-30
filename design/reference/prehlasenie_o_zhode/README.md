# Prehlásenie o zhode (atest 2.1) — reference from Erik (2026-10-30)

- `Prehlasenie_o_zhode_sablona.pdf` — the approved look (empty template, no customer data).
- `prehlasenie_o_zhode.py.txt` — Erik's generator (HTML + CSS rendered with Playwright/Chromium). Reference only:
  Smart Mail renders print documents with Jinja2 + WeasyPrint (`templates/print/`, DOCUMENTS_SPEC §4) — port the
  HTML/CSS there, do not add Playwright to the app image. Kept as `.txt` so it is never imported or linted.

Implementation: issue „Prehlásenie o zhode (atest 2.1) s pečiatkou pobočky“.
