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
# Docs must be off outside APP_ENV=dev (deploy uses APP_ENV=test)
code="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/api/docs || true)"
[[ "$code" == "404" ]] || { echo "api/docs má byť 404 mimo dev (dostal $code)"; exit 1; }
code="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/api/openapi.json || true)"
[[ "$code" == "404" ]] || { echo "api/openapi.json má byť 404 mimo dev (dostal $code)"; exit 1; }

# CI/vps nginx must not map CF-Connecting-IP (spoofable); Caddy template must strip it.
grep -q 'proxy_add_x_forwarded_for' "$ROOT/deploy/nginx-deploy.conf"
if grep -q 'http_cf_connecting_ip' "$ROOT/deploy/nginx-deploy.conf"; then
  echo "CI/vps nginx-deploy.conf nesmie používať CF-Connecting-IP"; exit 1
fi
grep -q 'header_up -CF-Connecting-IP' "$ROOT/deploy/Caddyfile.tpl" \
  || { echo "Caddyfile.tpl musí stripovať CF-Connecting-IP"; exit 1; }

# Second install must not wipe .env and must stay silent about prompts
SUM1="$(sha256sum "$SMARTMAIL_ENV_FILE" | awk '{print $1}')"
OUT_REINSTALL="$("$ROOT/deploy/install.sh" 2>&1)"
echo "$OUT_REINSTALL" | grep -Fq 'Nastavenia ponechávam z .env' \
  || { echo "druhé install.sh nevypísalo ponechanie .env"; exit 1; }
SUM2="$(sha256sum "$SMARTMAIL_ENV_FILE" | awk '{print $1}')"
[[ "$SUM1" == "$SUM2" ]] || { echo "install.sh prepísal .env"; exit 1; }

echo "=== CI smoke: update ==="
"$ROOT/deploy/update.sh"
curl -fsS http://127.0.0.1:8080/readyz
GOOD_SHA="$(cat "$SMARTMAIL_STATE_DIR/last_good_sha")"
BRANCH="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)"
[[ "$BRANCH" != "HEAD" ]] || { echo "po update sme v detached HEAD"; exit 1; }

echo "=== CI smoke: update → simulated failure → rollback → next update ==="
set +e
SMARTMAIL_UPDATE_FAIL=1 "$ROOT/deploy/update.sh"
FAIL_RC=$?
set -e
[[ "$FAIL_RC" -ne 0 ]] || { echo "očakávané zlyhanie update.sh nenastalo"; exit 1; }
AFTER_ROLLBACK="$(git -C "$ROOT" rev-parse HEAD)"
[[ "$AFTER_ROLLBACK" == "$GOOD_SHA" ]] || {
  echo "rollback neobnovil SHA ($AFTER_ROLLBACK != $GOOD_SHA)"; exit 1
}
BRANCH_AFTER="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)"
[[ "$BRANCH_AFTER" != "HEAD" ]] || { echo "po rollback sme v detached HEAD"; exit 1; }
[[ "$BRANCH_AFTER" == "$BRANCH" ]] || {
  echo "po rollback iná vetva ($BRANCH_AFTER != $BRANCH)"; exit 1
}
# Next update must succeed (still on the branch)
"$ROOT/deploy/update.sh"
curl -fsS http://127.0.0.1:8080/readyz
[[ "$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)" != "HEAD" ]] || {
  echo "po druhom update sme v detached HEAD"; exit 1
}

echo "=== CI smoke: status (no secrets) ==="
"$ROOT/deploy/status.sh" | tee /tmp/smartmail-status.txt
# Fail if a secret-looking line leaked (Fernet / long hex keys)
if grep -EEiq 'APP_SECRET_KEY|APP_ENCRYPTION_KEY|POSTGRES_PASSWORD|BEGIN PRIVATE|eyJ' /tmp/smartmail-status.txt; then
  echo "status.sh vyzradil tajomstvo"; exit 1
fi

echo "CI smoke OK"
