# ADR-001: Technology stack and repository layout

- Status: accepted (Phase 0, 26 October 2026)
- Context: CLAUDE.md §2–§3, DECISIONS D1–D24

## Decision
- **Backend** `app/`: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 async + Alembic, PostgreSQL 16 with pgvector,
  unaccent and pgcrypto (migration `0001`), Redis + ARQ worker, structlog JSON logs. Dependencies managed with **uv**
  (`pyproject.toml` + `uv.lock`, Python pinned to 3.12).
- **Money bridge** `bridge/`: separate FastAPI service with its own `pyproject.toml`/`uv.lock` and Docker image, because
  it is deployed in the customer's LAN next to Money S4 and is the only component allowed to talk to Money.
  Default backend is `mock`; agenda label `TEST`. Writes are disabled in code until Phase 4.
- **Web** `web/`: React 18 + Vite + TypeScript (strict) + Tailwind 3. Tailwind colours are generated from
  `src/styles/tokens.css`, which is a byte-for-byte copy of `design/tokens.css` (checked in CI and in
  `tests/test_quality_gates.py`). i18next with Slovak only (`src/i18n/sk.json`). Libraries listed in CLAUDE.md §2 that
  Phase 0 does not need yet (shadcn/ui, TanStack Query, React Router, Zustand, TipTap, pdf.js, cmdk,
  vite-plugin-pwa, Lucide) are added in Phase 1 when the first screen uses them.
- **Print documents**: reference renderer `tools/render_print.py` (WeasyPrint 70.0 pinned) with Liberation Sans Narrow
  committed in `templates/print/fonts/`; golden tests rasterise with poppler `pdftoppm -r 150`, the same tool that
  produced `fixtures/documents/*.png`.
- **Local stack**: Docker Compose with Postgres (pgvector image), Redis, S3 storage (SeaweedFS — ADR-002), ClamAV, Mailpit, bridge, app, worker,
  web (nginx serving the build and proxying `/api`, `/healthz`, `/readyz`).
- **CI**: GitHub Actions — backend, bridge and web jobs (lint, format, strict types, tests, dependency audit) and a
  `docker compose up --wait` smoke test. ClamAV is not started in CI (signature download takes minutes).
- **Design**: the Figma file is the visual source of truth (D24); `.mcp.json` registers the Figma MCP server so the
  coding agent can read frames listed in `docs/FIGMA_MAP.md`.

## Consequences
- Two Python lockfiles must be updated independently (`uv lock` in the root and in `bridge/`).
- Golden print tests need poppler-utils, fontconfig and the committed fonts; CI installs them explicitly.
- Changing colours means editing `design/build_tokens.py` and running `make tokens`, never editing CSS by hand.
