# ADR-003: Mailbox login, server-side sessions and login protection

- Status: proposed (Phase 1a, 26 October 2026) — choices marked ⚠ need the customer's confirmation before 1b
- Context: CLAUDE.md §2/§11 and PRODUCT_SPEC §2.0 require a login like Roundcube (mailbox e-mail + password checked by
  the IMAP server), server-side sessions with CSRF, a login rate limit, "Zostať prihlásený" and logout everywhere when
  the mailbox password changes. The plan leaves several details open; this ADR records what 1a implements.

## Decision
1. **Login = IMAP LOGIN** against the server Roundcube uses (`IMAP_LOGIN_HOST/PORT/SECURITY`, TLS by default, plain
   text refused in prod). Smart Mail never verifies a password itself.
2. ⚠ **Only registered accounts can sign in.** A correct IMAP login for an address without an `accounts` row gets the
   same "Nesprávny e-mail alebo heslo." Accounts are created by an admin (`python -m app.cli add-account`, later
   Settings 10/11). Alternative: auto-create accounts for `INTERNAL_DOMAINS`.
3. ⚠ **One login server for everybody** until Settings › Schránky (per-mailbox IMAP config) exists. The mailbox
   password is not stored in 1a; storing it encrypted (needed by the background sync in 1c) is a 1c decision.
4. **Sessions** live in PostgreSQL (`sessions`); the cookie `sm_session` (HttpOnly, SameSite=Lax, Secure on https)
   holds a random token, the table only its SHA-256. Idle timeout 12 h (sliding); "Zostať prihlásený" = fixed
   30 days, lowered by the branch setting `remember_days` (30/7/1). The session token is rotated after 2FA.
5. **CSRF**: signed double-submit token (`sm_csrf` cookie + `X-CSRF-Token` header, HMAC bound to the session token)
   on every unsafe `/api` request, including login.
6. **Password change**: the account stores a salted scrypt fingerprint of the last mailbox password. A successful IMAP
   login with a different password revokes all other sessions with reason `password_changed`; those clients get
   `401 {reason: password_changed}` and show W1c. `revoke_account_sessions()` is also what the mailbox sync (1c) will
   call when its IMAP login fails with an authentication error.
7. ⚠ **Rate limit** (Redis): 5 failed attempts per account → 5 min lock; 20 per client IP in 5 min (branch PCs behind
   one NAT share an IP). Wrong 2FA codes count too; "mail server unavailable" does not. The real client IP comes
   from nginx via `X-Forwarded-For` (`FORWARDED_ALLOW_IPS`).
8. **2FA (TOTP, RFC 6238)** with the standard library, secret encrypted with Fernet (`APP_ENCRYPTION_KEY`), replay
   protection per time step, 10 single-use backup codes (hashed), 5 wrong codes cancel the pending login, "Zapamätať
   zariadenie na 30 dní" = signed HttpOnly cookie. Enrolment (QR code) is Settings 09 (Phase 1f).
9. **Audit log** is append-only in the database (trigger blocks UPDATE/DELETE/TRUNCATE for every role); `audit()`
   rejects detail keys such as `password`, `code`, `token`.
10. **Maintenance mode** is a Redis flag (`python -m app.cli maintenance on --until …`); the API answers
    `503 {code: maintenance, until}` and the web shows W17.

## Consequences
- New dependencies from the CLAUDE.md stack: `imapclient`, `cryptography` (Fernet); web: `react-router-dom`,
  `@tanstack/react-query`, `lucide-react`, `@playwright/test`.
- OIDC (Microsoft/Google) is not implemented yet; the W1 row "Prihlásiť cez Microsoft / Google" stays hidden.
