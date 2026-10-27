#!/usr/bin/env bash
# Nightly backup of Postgres + SeaweedFS data dir. Keep 7 days. No secrets/mail bodies in logs.
set -euo pipefail
# shellcheck source=lib.sh
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"

[[ -f "$ENV_FILE" ]] || die "chýba $ENV_FILE"
mkdir -p "$BACKUP_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$BACKUP_DIR/smartmail-$STAMP"
mkdir -p "$OUT"

echo "Záloha $STAMP → $OUT"
"${COMPOSE[@]}" exec -T db pg_dump -U smartmail -d smartmail -Fc >"$OUT/db.dump"

# SeaweedFS volume is named project_s3-data; copy via a helper container if possible.
if docker volume ls --format '{{.Name}}' | grep -q 's3-data'; then
  VOL="$(docker volume ls --format '{{.Name}}' | grep 's3-data' | head -1)"
  docker run --rm -v "$VOL:/data:ro" -v "$OUT:/out" alpine:3.20 \
    tar -C /data -czf /out/s3-data.tgz .
fi

chmod -R go-rwx "$OUT"
# prune older than 7 days
find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -mtime +7 -exec rm -rf {} +
echo "Hotovo."
