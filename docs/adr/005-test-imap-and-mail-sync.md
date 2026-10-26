# ADR-005: Local TEST IMAP server and mail sync (Phase 1c)

- Status: accepted (Phase 1c, 26 October 2026)
- Context: CLAUDE.md §5 (IDLE on INBOX, 2-min poll of other subscribed folders, SPECIAL-USE, QUOTA), SCREENS_SPEC
  G1–G7 / W2 folder column, DECISIONS D21 (customer folders). Product mail must keep working when Money is down; the
  customer's live mailboxes (eshop@, info@, branch) must never be used in development.

## Decision
1. **Local TEST server** = compose service `imap-test` (Dovecot): IMAP on 143 (host 1143), ManageSieve 4190,
   SPECIAL-USE Drafts/Sent/Junk/Trash, IDLE, CONDSTORE, QUOTA. Fictional users only
   (`pilot@`/`plna@`/`senica@smartmail.test`); seed tool `tools/seed_test_imap.py` / `make imap-seed` fills the
   Roundcube folder set (Doručená pošta … Trenčín) with fictional messages. `plna@` has a 2 MB quota so ≥ 90 % can
   be tested. Never a stand-in for mail2.nameserver.sk.
2. **Host guard**: outside `APP_ENV=prod`, sync and folder mutations connect only to `localhost` / `127.0.0.1` /
   `::1` / `imap-test` unless `MAIL_SYNC_ALLOW_REAL_SERVER=true` (the dedicated TEST mailbox of 1f). Live company
   mailboxes are refused in code.
3. **Sync model**:
   - First open after login (`sync_state=new`) runs a full sync inline so the folder column is filled.
   - Worker: one `InboxWatcher` thread per mailbox (IDLE, renew every `MAIL_IDLE_RENEW_SECONDS`); cron every minute
     enqueues poll of other subscribed folders every `MAIL_POLL_SECONDS` (or full sync when no watcher).
   - Envelope-only fetch (UID lists in batches of `MAIL_SYNC_BATCH`); CONDSTORE for flag changes; Redis lock
     `smartmail:mail-sync:{id}`; ARQ job id with `keep_result=0` so re-enqueue works.
   - Auth failure during sync → `auth_failed`, clear encrypted password, revoke sessions (`password_changed`), audit
     `mail.sync_auth_failed`.
4. **Folder column API**: `GET /api/mail/mailboxes/{ref}/folders` returns ordered folders (special first with SK names
   in the web, then own folders Slovak-alphabetically, children under parents), quota `{percent, level}` and sync
   state. Mutations (create/rename/delete/mark-read/empty/compact) need `ActivePerson`, re-sync after IMAP, audit.
5. **Real-server integration** (`tests/integration/test_real_mailbox.py`): runs only when `REAL_IMAP_TEST_*` are set
   in `.env`; skips with a clear reason otherwise. Refuses eshop/info/branch addresses. Read-only (login, IDLE,
   QUOTA, ManageSieve greeting). Listed as an open risk until the customer provides the TEST mailbox.
6. **UI refresh**: the web re-fetches folders every 30 s; WebSockets for live push arrive in Phase 5. Money ● in the
   quota row is grey "vypnuté" until Phase 3.

## Consequences
- Dev login defaults to `IMAP_LOGIN_HOST=imap-test` / port 143 / security none; production `.env` sets
  mail2.nameserver.sk:993/ssl. CI builds `imap-test`, seeds it and runs the IMAP suite with `REQUIRE_IMAP=1`.
- PersonChip always opens a menu with at least Môj profil and Odhlásiť (even with one person); below 820 px height
  Tmavý režim and O systéme move into that menu (G1).
- List / reading pane / dark mode / compose / settings editors stay for 1d–1f; 1c ships the shell and the folder
  column only.
