#!/usr/bin/env bash
# Shared helpers for deploy/*.sh (ADR-010). Never print secrets or mail bodies.
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$DEPLOY_DIR/.." && pwd)"
ENV_FILE="${SMARTMAIL_ENV_FILE:-$DEPLOY_DIR/.env}"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$DEPLOY_DIR/docker-compose.yml")
BACKUP_DIR="${SMARTMAIL_BACKUP_DIR:-/var/backups/smartmail}"
STATE_DIR="${SMARTMAIL_STATE_DIR:-$DEPLOY_DIR/.state}"

die() { echo "Chyba: $*" >&2; exit 1; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "chýba príkaz: $1"
}

# TCP connect probe (3 s). Returns 0 when the port accepts a connection.
probe_tcp() {
  local host="$1" port="$2"
  # Prefer bash /dev/tcp; fall back to timeout+bash if needed.
  if timeout 3 bash -c "exec 3<>/dev/tcp/${host}/${port}" 2>/dev/null; then
    return 0
  fi
  return 1
}

# Probe IMAP 993, SMTP 465 and ManageSieve 4190. Never fails the install — Slovak report only.
# 4190 down must not block; IMAP/SMTP failures are reported without wiping an existing .env.
probe_mail_ports() {
  local host="${1:-}"
  [[ -n "$host" ]] || return 0
  echo "Kontrolujem poštový server ${host}…"
  if probe_tcp "$host" 993; then
    echo "IMAP (993/SSL): OK"
  else
    echo "IMAP: server nedostupný na porte 993 – prihlásenie a synchronizácia pošty nemusia fungovať"
  fi
  if probe_tcp "$host" 465; then
    echo "SMTP (465/SSL): OK"
  else
    echo "SMTP: server nedostupný na porte 465 – odosielanie nemusí fungovať (skúste aj 587 STARTTLS v .env)"
  fi
  if probe_tcp "$host" 4190; then
    echo "Filtre / ManageSieve (4190): OK"
  else
    echo "Filtre: server nedostupný na porte 4190 – Filtre a Mimo kancelárie nebudú fungovať"
  fi
}

rand_hex() { openssl rand -hex "${1:-32}"; }

# Fernet-compatible key without importing cryptography.
fernet_key() {
  openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n'
}

# Phase 3f (#144): Ed25519 key pair for the single-use approval tokens of Money writes. The private key stays in
# deploy/.env (chmod 600) as one base64 line; it is never printed. Only the public key is printed for the bridge.
ed25519_private_b64() {
  openssl genpkey -algorithm ed25519 2>/dev/null | base64 | tr -d '\n'
}

ed25519_public_b64() {
  # stdin: base64 of the private PEM → base64 of the public PEM
  base64 -d | openssl pkey -pubout 2>/dev/null | base64 | tr -d '\n'
}

prompt() {
  # prompt "Otázka" "default" → writes answer to REPLY
  local q="$1" def="${2:-}"
  if [[ -n "${SMARTMAIL_CI:-}" ]]; then
    REPLY="$def"
    return
  fi
  if [[ -n "$def" ]]; then
    read -r -e -p "$q [$def]: " REPLY || true
    REPLY="${REPLY:-$def}"
  else
    read -r -e -p "$q: " REPLY || true
  fi
}

prompt_secret() {
  local q="$1"
  if [[ -n "${SMARTMAIL_CI:-}" ]]; then
    REPLY="${2:-}"
    return
  fi
  read -r -s -p "$q: " REPLY || true
  echo
}

ensure_docker() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    return
  fi
  echo "Inštalujem Docker…"
  need_cmd curl
  curl -fsSL https://get.docker.com | sh
  if command -v systemctl >/dev/null 2>&1; then
    systemctl enable --now docker || true
  fi
  docker compose version >/dev/null 2>&1 || die "Docker Compose plugin nie je dostupný"
}

ensure_ufw_installed() {
  # Returns 0 when ufw is available (installs via apt on Ubuntu/Debian when missing).
  if command -v ufw >/dev/null 2>&1; then
    return 0
  fi
  if command -v apt-get >/dev/null 2>&1; then
    echo "Inštalujem ufw…"
    DEBIAN_FRONTEND=noninteractive apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ufw
  fi
  command -v ufw >/dev/null 2>&1
}

render_edge_configs() {
  # Nginx: CF-Connecting-IP only in tunnel mode. VPS/CI ignore it (spoofable via Caddy).
  # Write to nginx-active.conf (gitignored) — never overwrite templates committed in git.
  # Caddy (vps): strip CF-Connecting-IP before proxying to web.
  local mode="${DEPLOY_MODE:-ci}"
  case "$mode" in
    tunnel)
      cp "$DEPLOY_DIR/nginx-deploy.tunnel.conf" "$DEPLOY_DIR/nginx-active.conf"
      ;;
    vps | ci)
      cp "$DEPLOY_DIR/nginx-deploy.vps.conf" "$DEPLOY_DIR/nginx-active.conf"
      ;;
    *)
      die "neznámy režim: $mode"
      ;;
  esac
  if [[ "$mode" == "vps" ]]; then
    local host_for_caddy="${APP_HOSTNAME:-localhost}"
    sed "s/__APP_HOSTNAME__/${host_for_caddy}/g" "$DEPLOY_DIR/Caddyfile.tpl" >"$DEPLOY_DIR/Caddyfile"
  fi
}

reload_edge_configs() {
  # A running nginx/Caddy keeps the old config when only the bind-mounted file changed (no image rebuild):
  # reload them, after a syntax check, so a new rule (e.g. the .mjs MIME type, #59) takes effect.
  local nginx_before="$1" caddy_before="$2"
  local nginx_now caddy_now
  nginx_now="$(sha256sum "$DEPLOY_DIR/nginx-active.conf" | awk '{print $1}')"
  if [[ "$nginx_now" != "$nginx_before" ]]; then
    echo "nginx konfigurácia sa zmenila – načítavam ju znova…"
    "${COMPOSE[@]}" exec -T web nginx -t
    "${COMPOSE[@]}" exec -T web nginx -s reload
  fi
  if [[ "${DEPLOY_MODE:-ci}" == "vps" && -f "$DEPLOY_DIR/Caddyfile" ]]; then
    caddy_now="$(sha256sum "$DEPLOY_DIR/Caddyfile" | awk '{print $1}')"
    if [[ "$caddy_now" != "$caddy_before" ]]; then
      echo "Caddy konfigurácia sa zmenila – načítavam ju znova…"
      "${COMPOSE[@]}" --profile vps exec -T caddy caddy reload --config /etc/caddy/Caddyfile
    fi
  fi
}

compose_up() {
  local profiles=()
  case "${DEPLOY_MODE:-ci}" in
    vps) profiles=(--profile vps) ;;
    tunnel) profiles=(--profile tunnel) ;;
    ci) profiles=() ;;
    *) die "neznámy režim: ${DEPLOY_MODE:-}" ;;
  esac
  render_edge_configs
  # ClamAV downloads signatures for minutes — skip in CI smoke.
  if [[ -z "${SMARTMAIL_CI:-}" ]]; then
    :
  fi
  "${COMPOSE[@]}" "${profiles[@]}" up -d --build --remove-orphans "$@"
}

wait_healthy() {
  local url="${1:-http://127.0.0.1:8080/readyz}"
  local i
  for i in $(seq 1 90); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "Služby sú pripravené (${i}×5 s)."
      return 0
    fi
    sleep 5
  done
  die "timeout: $url neodpovedá"
}

save_git_sha() {
  mkdir -p "$STATE_DIR"
  git -C "$ROOT_DIR" rev-parse HEAD >"$STATE_DIR/last_good_sha"
}

last_good_sha() {
  [[ -f "$STATE_DIR/last_good_sha" ]] && cat "$STATE_DIR/last_good_sha"
}
