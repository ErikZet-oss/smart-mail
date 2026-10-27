#!/usr/bin/env bash
# Pull, rebuild, migrate (app entrypoint), health-check; roll back to previous git SHA on failure.
set -euo pipefail
# shellcheck source=lib.sh
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"

cd "$ROOT_DIR"
[[ -f "$ENV_FILE" ]] || die "chýba $ENV_FILE — najprv spustite install.sh"
# shellcheck disable=SC1090
set -a && source "$ENV_FILE" && set +a
export DEPLOY_MODE="${DEPLOY_MODE:-ci}"

ensure_docker
need_cmd curl
need_cmd git

PREV="$(last_good_sha || true)"
CURRENT="$(git rev-parse HEAD)"
echo "Aktuálna verzia: $CURRENT"
[[ -n "$PREV" ]] || PREV="$CURRENT"

echo "git pull…"
if [[ -z "${SMARTMAIL_CI:-}" ]]; then
  git pull --ff-only
else
  echo "(CI: git pull vynechaný)"
fi
NEW="$(git rev-parse HEAD)"
echo "Nová verzia: $NEW"

rollback() {
  echo "Obnova na predchádzajúcu verziu ($PREV)…" >&2
  git checkout -f "$PREV"
  if [[ -n "${SMARTMAIL_CI:-}" ]]; then
    "${COMPOSE[@]}" up -d --build --remove-orphans db redis s3 bridge app worker web
  else
    compose_up
  fi
  wait_healthy "http://127.0.0.1:8080/readyz" || true
  die "aktualizácia zlyhala — obnovené na $PREV"
}

trap 'rollback' ERR

if [[ -n "${SMARTMAIL_CI:-}" ]]; then
  "${COMPOSE[@]}" up -d --build --remove-orphans db redis s3 bridge app worker web
else
  compose_up
fi
wait_healthy "http://127.0.0.1:8080/readyz"
trap - ERR
save_git_sha
echo "Aktualizácia hotová. Smart Mail beží: ${APP_BASE_URL:-http://127.0.0.1:8080}"
