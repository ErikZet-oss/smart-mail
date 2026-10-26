# ADR-006: Message list, bodies and local storage (Phase 1d)

## Context
Phase 1d needs Roundcube-parity list and reading (Zoznam/Konverzácie, sanitized HTML, remote-image block,
attachments, toolbar, prefs). Raw RFC822 and attachment bytes must live somewhere before the S3 client is wired
(CLAUDE.md §2: local driver in dev).

## Decision
- Keep envelopes in `messages` as in 1c; add `threads`, lazy `body_*` columns, `attachments`, `user_settings`.
- Fetch RFC822 on first open (`ensure_body`), store under `STORAGE_PATH` with opaque keys (same shape a later S3
  driver can reuse).
- Sanitize HTML with `nh3`; rewrite remote `http(s)` images to a placeholder the UI can unlock.
- Thread keys: Message-ID graph (root id = own Message-ID or In-Reply-To / first References); else subject +
  participants; 30-day window at link time.
- List/UI prefs (SETTINGS 01a/01b) in `user_settings` JSON per person.

## Consequences
- Bodies are not fetched during envelope sync (keeps IDLE/poll light).
- ClamAV stays `skipped` until attachment scanning is wired; infected status is already refused on download.
- S3 remains the production target (ADR-002); swapping the storage driver does not change API callers.
