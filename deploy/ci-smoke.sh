#!/usr/bin/env bash
# CI: exercise install.sh + update.sh on a clean host without certificates or a tunnel (ADR-010).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export SMARTMAIL_CI=1
export SMARTMAIL_ENV_FILE="${SMARTMAIL_ENV_FILE:-$ROOT/deploy/.env.ci}"
export SMARTMAIL_STATE_DIR="${SMARTMAIL_STATE_DIR:-$ROOT/deploy/.state-ci}"
export SMARTMAIL_BACKUP_DIR="${SMARTMAIL_BACKUP_DIR:-$ROOT/deploy/.backups-ci}"
rm -f "$SMARTMAIL_ENV_FILE"
rm -rf "$SMARTMAIL_STATE_DIR" "$SMARTMAIL_BACKUP_DIR"
mkdir -p "$SMARTMAIL_STATE_DIR" "$SMARTMAIL_BACKUP_DIR"

echo "=== CI smoke: install ==="
"$ROOT/deploy/install.sh"
curl -fsS http://127.0.0.1:8080/readyz
curl -fsS http://127.0.0.1:8080/healthz
curl -fsS http://127.0.0.1:8080/ | grep -q 'id="root"'
# Second install must not wipe .env
SUM1="$(sha256sum "$SMARTMAIL_ENV_FILE" | awk '{print $1}')"
"$ROOT/deploy/install.sh"
SUM2="$(sha256sum "$SMARTMAIL_ENV_FILE" | awk '{print $1}')"
[[ "$SUM1" == "$SUM2" ]] || { echo "install.sh prepísal .env"; exit 1; }

echo "=== CI smoke: update ==="
"$ROOT/deploy/update.sh"
curl -fsS http://127.0.0.1:8080/readyz

echo "=== CI smoke: status (no secrets) ==="
"$ROOT/deploy/status.sh" | tee /tmp/smartmail-status.txt
# Fail if a secret-looking line leaked (Fernet / long hex keys)
if grep -EEiq 'APP_SECRET_KEY|APP_ENCRYPTION_KEY|POSTGRES_PASSWORD|BEGIN PRIVATE|eyJ' /tmp/smartmail-status.txt; then
  echo "status.sh vyzradil tajomstvo"; exit 1
fi

echo "CI smoke OK"
