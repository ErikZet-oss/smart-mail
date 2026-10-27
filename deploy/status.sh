#!/usr/bin/env bash
# Service state, free disk, last sync hint. Never prints secrets or mail bodies.
set -euo pipefail
# shellcheck source=lib.sh
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"

echo "=== Smart Mail — stav ==="
echo "Repo: $ROOT_DIR"
if git -C "$ROOT_DIR" rev-parse HEAD >/dev/null 2>&1; then
  echo "Git:  $(git -C "$ROOT_DIR" rev-parse --short HEAD) ($(git -C "$ROOT_DIR" log -1 --pretty=%s 2>/dev/null || true))"
fi
if [[ -f "$STATE_DIR/last_good_sha" ]]; then
  echo "Last good: $(cut -c1-12 "$STATE_DIR/last_good_sha")"
fi

echo
echo "— Docker služby —"
if [[ -f "$ENV_FILE" ]]; then
  "${COMPOSE[@]}" ps || true
else
  echo "(žiadny .env — ešte nebola inštalácia)"
fi

echo
echo "— Disk —"
df -h / /var/lib/docker 2>/dev/null || df -h /

echo
echo "— Zálohy —"
if [[ -d "$BACKUP_DIR" ]]; then
  ls -lah "$BACKUP_DIR" 2>/dev/null | tail -n +1 || true
else
  echo "(priečinok $BACKUP_DIR zatiaľ neexistuje)"
fi

echo
echo "— Health —"
if curl -fsS http://127.0.0.1:8080/readyz >/dev/null 2>&1; then
  echo "readyz: OK"
  curl -fsS http://127.0.0.1:8080/readyz || true
  echo
else
  echo "readyz: NEDOSTUPNÉ"
fi

echo
echo "— Posledná synchronizácia (DB, bez tiel správ) —"
if [[ -f "$ENV_FILE" ]] && "${COMPOSE[@]}" ps --status running 2>/dev/null | grep -q ' db '; then
  "${COMPOSE[@]}" exec -T db \
    psql -U smartmail -d smartmail -tAc \
    "select email, sync_state, coalesce(sync_error,''), coalesce(last_synced_at::text,'') from mailboxes order by email limit 20" \
    2>/dev/null || echo "(mailboxes ešte nie sú)"
else
  echo "(databáza nebeží)"
fi
