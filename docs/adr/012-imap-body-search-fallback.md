# ADR-012: Body search on the IMAP server as a fallback (issue #38)

- Status: proposed (pilot finding)
- Context: sync stores envelopes only and bodies are fetched on open (ADR-007). The local full-text index (ADR-009)
  therefore knows the body of **opened** messages only. Roundcube searches the body on the IMAP server, so the fields
  Telo / Celá správa returned fewer results than Roundcube (PRODUCT_SPEC §2.7 parity gap).

## Decision
1. `GET /api/search?server=true`: for the fields **Telo** (`BODY`) and **Celá správa** (`TEXT`) the backend also runs
   `UID SEARCH CHARSET UTF-8` on the IMAP server, on the folders of the same scope (current / subfolders / all,
   private folders as in ADR-009), one login per mailbox, `SELECT` read-only. The UIDs are merged into the local query
   (`folder_id = X AND uid = ANY(…)`), so ranking, paging, ACL and `deleted` stay in one place. Other fields never ask
   the server.
2. The **local index stays primary** and the first response is local only; the client then repeats the query with
   `server=true` and shows „Hľadá sa aj na serveri…“. No sync design change, no body prefetch (option 2 of #38 stays
   open if the server search is too slow on the pilot).
3. **Safety**: terms are reduced to word characters and `@ . _ + -` (max 10 words × 100 chars), because imapclient
   quotes only strings with a space / quote / backslash — `(` `)` `{` `%` `*` `]` or CR/LF could otherwise change the
   command. 8-bit terms go out as literals. Words are ANDed (`BODY a BODY b`), like the local search.
4. **Limits**: 15 s timeout (`server_search: "timeout"`), a failing folder is skipped (`"partial"`), an unreachable
   server or missing stored password gives `"unavailable"`; the local hits are always returned. At most 5 000 UIDs
   (the newest) per folder are merged. Same host guard as the sync (`sync_host_allowed`).
5. **One IMAP session per mailbox** (review #60): Dovecot limits sessions per user and IP
   (`mail_max_userip_connections`, default 10) and the sync, IDLE and Roundcube share them. A non-blocking Redis lock
   `smartmail:server-search:<mailbox>` (TTL = timeout + 5 s) allows one server search per mailbox; a second one gets
   `server_search: "busy"` („Prehľadávanie servera ešte beží – skúste o chvíľu.“) with the local hits. The thread is
   bounded: the IMAP socket timeout is the search timeout, and before each folder the remaining time is checked
   (`partial` when it is used up), so the session ends on its own soon after a request timed out.

## Consequences
- Accent folding differs between the two: on the local test Dovecot `paletovy` finds `paletový` but `trencin` does not
  find `Trenčín` (the local index folds both). Users still get every message the local index finds, plus what the
  server finds for unopened bodies.
- One extra IMAP login per mailbox per body search (only when the user searches Telo / Celá správa).
