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
  # Detached HEAD (GitHub PR merge checkout, or a bad prior rollback). Stay on this commit —
  # never jump to origin/main, which would drop the PR tree in CI.
  if [[ -n "${SMARTMAIL_CI:-}" ]]; then
    BRANCH="${SMARTMAIL_GIT_BRANCH:-ci-deploy}"
  else
    BRANCH="main"
  fi
  git checkout -B "$BRANCH" "$CURRENT"
fi
echo "Aktuálna verzia: $CURRENT (vetva $BRANCH)"
[[ -n "$PREV" ]] || PREV="$CURRENT"

echo "git pull…"
if [[ -z "${SMARTMAIL_CI:-}" ]]; then
  # Explicit remote + branch: a branch recreated by `checkout -B` has no upstream, and with several remote
  # branches a bare pull fails ("Cannot fast-forward to multiple branches", pilot 2026-10-31).
  git pull --ff-only origin "$BRANCH"
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

# Re-render nginx/Caddy from DEPLOY_MODE (vps strips CF-Connecting-IP; tunnel keeps it).
# Bind-mounted configs are not re-read by a running container, so remember whether they changed (pilot #59).
# A missing file (first run, or no Caddyfile in ci/tunnel mode) is an empty hash, not an error under pipefail.
file_hash() { if [[ -f "$1" ]]; then sha256sum "$1" | awk '{print $1}'; fi; }
NGINX_BEFORE="$(file_hash "$DEPLOY_DIR/nginx-active.conf")"
CADDY_BEFORE="$(file_hash "$DEPLOY_DIR/Caddyfile")"
render_edge_configs

# Pilot 2026-11-23: a full disk stopped Postgres in the middle of an update. Old backups first, then a hard limit.
prune_backups "$BACKUP_DIR"
FREE="$(free_gb "$BACKUP_DIR")"
if [[ -z "${SMARTMAIL_CI:-}" && "$FREE" -lt "$MIN_FREE_GB" ]]; then
  trap - ERR
  echo "Na disku je len ${FREE} GB voľného miesta (treba aspoň ${MIN_FREE_GB} GB) – aktualizácia sa nespustila." >&2
  echo "Zistite, čo zaberá miesto:  du -xsh /var/* 2>/dev/null | sort -h | tail" >&2
  echo "Staré zálohy:               ls -1dt ${BACKUP_DIR}/smartmail-*" >&2
  exit 1
fi

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
reload_edge_configs "$NGINX_BEFORE" "$CADDY_BEFORE"
trap - ERR
save_git_sha
# Pilot 2026-11-20/23: build cache and replaced images filled the disk — drop unused images and build cache older
# than 3 days (recent cache keeps the next build fast). Never fails the update.
docker image prune -f >/dev/null 2>&1 || true
docker builder prune -f --filter until=72h >/dev/null 2>&1 || true
echo "Voľné miesto na disku: $(free_gb "$BACKUP_DIR") GB"
echo "Aktualizácia hotová. Smart Mail beží: ${APP_BASE_URL:-http://127.0.0.1:8080}"
