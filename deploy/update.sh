#!/usr/bin/env bash
# Pull, backup, rebuild, migrate (app entrypoint), health-check.
# On failure: git reset --hard to previous SHA on the same branch (not detached) and restart.
# Migrations are NOT rolled back automatically — print how to restore from backup.
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
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$BRANCH" == "HEAD" ]]; then
  BRANCH="main"
  git checkout "$BRANCH" 2>/dev/null || git checkout -B main
fi
echo "Aktuálna verzia: $CURRENT (vetva $BRANCH)"
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
  trap - ERR
  echo "Obnova na predchádzajúcu verziu ($PREV) na vetve $BRANCH…" >&2
  git checkout "$BRANCH"
  git reset --hard "$PREV"
  if [[ -n "${SMARTMAIL_CI:-}" ]]; then
    "${COMPOSE[@]}" up -d --build --remove-orphans db redis s3 bridge app worker web
  else
    compose_up
  fi
  wait_healthy "http://127.0.0.1:8080/readyz" || true
  echo >&2
  echo "Migrácie sa automaticky nevracajú." >&2
  echo "Obnova databázy zo zálohy (ak treba):" >&2
  echo "  Najnovšia záloha je v ${BACKUP_DIR}/smartmail-*/db.dump" >&2
  echo "  docker compose --env-file $ENV_FILE -f $DEPLOY_DIR/docker-compose.yml exec -T db \\" >&2
  echo "    pg_restore -U smartmail -d smartmail --clean --if-exists < ${BACKUP_DIR}/smartmail-YYYYMMDD/db.dump" >&2
  die "aktualizácia zlyhala — kód obnovený na $PREV (vetva $BRANCH)"
}

trap 'rollback' ERR

# Backup before migrations (alembic runs in the app container entrypoint).
echo "Záloha pred migráciou…"
"$DEPLOY_DIR/backup.sh"

# CI-only hook: simulate a failed update to exercise rollback (ci-smoke.sh).
if [[ "${SMARTMAIL_UPDATE_FAIL:-}" == "1" ]]; then
  die "simulované zlyhanie aktualizácie (SMARTMAIL_UPDATE_FAIL=1)"
fi

if [[ -n "${SMARTMAIL_CI:-}" ]]; then
  "${COMPOSE[@]}" up -d --build --remove-orphans db redis s3 bridge app worker web
else
  compose_up
fi
wait_healthy "http://127.0.0.1:8080/readyz"
trap - ERR
save_git_sha
echo "Aktualizácia hotová. Smart Mail beží: ${APP_BASE_URL:-http://127.0.0.1:8080}"
