# ADR-007: Compose, S3 storage and BODY.PEEK (Phase 1e)

- Status: accepted (Phase 1e)
- Context: Phase 1d stored bodies on the local filesystem and fetched with `RFC822` as a fallback. Compose needs
  outbound SMTP, identities, drafts and durable attachment storage. Opening a message must not mark it `\Seen`.

## Decision
1. **Fetch bodies with `BODY.PEEK[]` only** — never `RFC822`.
2. **Object storage uses the S3 API** (`STORAGE_BACKEND=s3`, SeaweedFS in compose, ADR-002). `STORAGE_BACKEND=local`
   remains for isolated unit tests only.
3. **Compose** stores drafts in PostgreSQL (`compose_drafts` / `compose_attachments`), identities and Odpovede in DB;
   outbound mail goes through `aiosmtplib` (Mailpit in dev/CI). Undo send is an ARQ deferred job (`UNDO_SEND_SECONDS`).
4. **ClamAV** stays deferred to Phase 1h (`av_status=skipped`).

## Consequences
- Callers keep opaque `storage_key` strings; swapping S3 endpoints does not change the API.
- Compose UI: W4 / W4b / W4d (W4a AI panel not in Phase 1); Reply/Forward open `/compose`.
