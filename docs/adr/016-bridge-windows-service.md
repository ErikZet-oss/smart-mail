# ADR-016: Money bridge on the office Windows Server (NSSM service + Cloudflare Tunnel)

- Status: accepted (Erik, #150 — 30. 10. 2026)
- Context: Money S4 runs on a physical **Windows Server** in the office, 24/7. The app runs on the VPS (ADR-010).
  Only the bridge may hold Money credentials (CLAUDE.md §7), and the office must not open an inbound port.

## Decision

1. **The bridge runs on the Money server**, in the LAN next to Money, bound to `127.0.0.1:8100`.
2. **Windows service through NSSM** (variant B, approved as a new tool). Python 3.12 + uv, a virtualenv in
   `C:\SmartMail\bridge`, service `SmartMailBridge`:
   - automatic start;
   - runs as `NT AUTHORITY\LocalService`;
   - stdout/stderr to `C:\SmartMail\bridge\logs`, rotated by NSSM at 10 MB.
3. **Connection app ↔ bridge: Cloudflare Tunnel** (`cloudflared` as a Windows service, outbound only):
   - public hostname e.g. `money-bridge.<domain>` → `http://127.0.0.1:8100`;
   - the hostname is protected by **Cloudflare Access with a service token**; the app sends
     `CF-Access-Client-Id` / `CF-Access-Client-Secret` (`BRIDGE_CF_ACCESS_CLIENT_ID` / `…_SECRET`);
   - **HMAC** (ADR in MONEY_API §6) stays on top, so a leaked Access token alone is not enough.
4. **Secrets** live only in `C:\SmartMail\bridge\.env`. Its ACL allows only Administrators, SYSTEM and the service
   account. Erik types the secrets into the installer prompts — never in GitHub or chat.
5. `MONEY_AGENDA_LABEL=TEST` is written by the installer. The bridge refuses `MONEY_BACKEND=api` on any other agenda
   (3a). Writes stay disabled (Phase 3: read-only, 3f waits for Erik's answer in #144).
6. **Install / update**: `deploy/bridge-windows/install-bridge.ps1` and `update-bridge.ps1` (PowerShell 5.1+,
   run as Administrator from the extracted repository ZIP). Update keeps `.env` and the logs.

## Rejected alternatives

- **Docker on the Windows Server** (variant A): Docker Desktop / WSL2 on a production Windows Server adds a
  licence and a second OS layer for a single small Python service — rejected by Erik.
- WireGuard VPN office ↔ VPS: needs a router change in the office.
- An open port with TLS + IP allowlist: an inbound port into the office LAN.
- The bridge on the VPS reaching Money through a tunnel: Money credentials would leave the LAN.

## Consequences

- The app needs `BRIDGE_URL=https://money-bridge.<domain>` and the two Access variables on the VPS.
- `money_probe.py` runs on the same server (standard library only) — README › „Spustenie money_probe.py na Windows
  Serveri“.
- Monitoring: the app calls `/healthz` and `/readyz` (Settings 13a); NSSM restarts the service when it stops.
