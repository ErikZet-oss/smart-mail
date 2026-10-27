# ADR-010: VPS deploy with Caddy or Cloudflare Tunnel

- Status: accepted (Phase 1h-f / PR 6)
- Context: Pilot runs on a rented VPS (Hetzner CX33 or netcup VPS 1000, Ubuntu 24.04, 8 GB). The company
  Hyper-V Linux VM is only for production later. Public access needs HTTPS without putting Postgres, Redis,
  S3, the API or the bridge on the public internet. Docker publishes ports that bypass `ufw`, so anything
  except the edge must bind to `127.0.0.1`.

## Decision

1. **Two edge modes** (chosen at `deploy/install.sh`):
   - **vps** — Caddy container publishes **80/443**, obtains Let's Encrypt certificates for the app hostname,
     reverse-proxies to `web:80`. All other compose ports bind to `127.0.0.1` only.
   - **tunnel** — Cloudflare Tunnel (`cloudflared`) container; public hostname routes to `http://web:80`.
     No inbound ports required on the VPS.
2. **Caddy and cloudflared are approved new services** for this deployment path (they are not part of the
   local Phase 0 compose). They are never required for `docker compose` developer workflows.
   Images are **pinned** to current 2026 versions (`caddy:2.11.7-alpine`, `cloudflare/cloudflared:2026.10.4`) —
   never `:latest`.
3. **Test / pilot stack** (`APP_ENV=test`): real IMAP/SMTP (`MAIL_SYNC_ALLOW_REAL_SERVER=true`,
   `MAIL_SEND_ALLOW_REAL_SERVER=true`) with `MAIL_SEND_TEST_ALLOWLIST` and `LOGIN_ALLOWLIST`. No Mailpit,
   no `imap-test`. Money bridge stays **mock**; UI Money surfaces stay hidden (`FEATURE_MONEY=false`).
   `/api/docs` and `/api/openapi.json` are disabled outside `APP_ENV=dev`.
4. **Secrets** are generated into `.env` (`chmod 600`) on first install. A second `install.sh` run never
   overwrites an existing `.env` or volumes and prints
   `Nastavenia ponechávam z .env, na zmenu upravte deploy/.env a spustite update.sh` (no prompts).
5. **Updates** via `deploy/update.sh`: `git pull`, **`backup.sh` before migrations**, rebuild, migrate
   (app entrypoint), health check. On failure: `git checkout <branch> && git reset --hard <prev-sha>`
   (stay on the branch — never a detached HEAD) and restart. Migrations are **not** rolled back
   automatically; the script prints how to `pg_restore` from the backup.
6. **Backups**: nightly dump of Postgres + object storage under `/var/backups/smartmail`, keep 7 days;
   also taken immediately before each update’s migrations.
7. **Client IP (D26)**: nginx must not overwrite `X-Forwarded-For` with `$remote_addr` alone. Use
   `$proxy_add_x_forwarded_for`, `real_ip` only from the Docker network, `X-Forwarded-Proto` from Caddy.
   **`CF-Connecting-IP` only in tunnel mode** (separate nginx conf). In vps mode Caddy strips it
   (`header_up -CF-Connecting-IP`) so a client cannot spoof the login IP limit / audit.
   `FORWARDED_ALLOW_IPS` is the Docker private ranges — never `*`.
8. **Caddy** sets `Strict-Transport-Security "max-age=31536000"` and the usual security headers for the
   whole site including `/api`, and strips `CF-Connecting-IP` toward nginx.
9. **ufw** is enabled by `install.sh`: allow **22/80/443** in vps mode, **only 22** in tunnel mode.

## Consequences

- Pilot operators need a DNS A record (vps) or a Cloudflare Tunnel token (tunnel), plus a GitHub deploy key
  for `git pull` on the VPS.
- Production Hyper-V later can reuse the same scripts; only mode / hostname / secrets change.
- CI exercises `install.sh` / `update.sh` in a clean Ubuntu runner without certificates or a tunnel
  (`SMARTMAIL_CI=1`), including update → simulated failure → rollback → next update succeeds.
  The deploy smoke job does **not** depend on the backend/web unit jobs so it always runs.
