# ADR-008: Send guard and Settings (Phase 1f)

- Status: accepted (Phase 1f)
- Context: Compose (1e) could send via any SMTP host. Settings sections 01–06, 09, 09b, 10–12 need ManageSieve,
  HTML signatures (D22), and admin CRUD for branches / persons / mailboxes.

## Decision
1. **Send guard** mirrors `MAIL_SYNC_ALLOW_REAL_SERVER`: outside `APP_ENV=prod`, SMTP only to Mailpit/localhost
   (`mailpit`, `localhost`, `127.0.0.1`, `::1`, `imap-test`) unless `MAIL_SEND_ALLOW_REAL_SERVER=true`. Recipients
   must be `@smartmail.test` or listed in `MAIL_SEND_TEST_ALLOWLIST` — even when the real-SMTP flag is on.
2. **W4e** (edit signature for this message) ships in 1f; **W4c** schedule and **W4f** popup move to **1h**.
3. Settings are driven by `settings_schema.json` / `web/src/features/settings/schema.ts` (CI snapshot vs SETTINGS_SPEC
   sections in Phase 1f). Filtre + Mimo kancelárie use ManageSieve (`sievelib`) with Roundcube script names
   `roundcube` / `vacation`.
4. Until `test@smartsro.sk` credentials exist, 1f is tested against local `imap-test`; `REAL_IMAP_TEST_*` stays skipped.

## Consequences
- Live customer mailboxes (eshop@, info@, branch) cannot receive or be used as SMTP targets outside prod.
- Signature HTML editors expose `<>` Zdrojový kód (D22) in identity, branch template, and W4e.
