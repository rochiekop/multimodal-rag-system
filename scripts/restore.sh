#!/usr/bin/env bash
# Restore a folder made by backup.sh over the current data. Destructive: asks for confirmation.
set -euo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/lib.sh"

dir="${1:?usage: scripts/restore.sh <backup folder> [--yes]}"
[ -f "$dir/postgres.dump" ] || { echo "error: $dir has no postgres.dump" >&2; exit 1; }
name="$(basename "$dir")"
if [ "${2:-}" != "--yes" ]; then
  read -r -p "This replaces ALL current data with backup '$name'. Type the folder name to continue: " answer
  [ "$answer" = "$name" ] || { echo "aborted"; exit 1; }
fi
pg_user="$(env_value POSTGRES_USER)"
pg_db="$(env_value POSTGRES_DB)"
collection="$(qdrant_collection)"

echo "Stopping the app services"
compose stop caddy frontend worker worker-eval api phoenix
compose up -d --wait postgres qdrant redis

echo "Restoring Postgres"
compose exec -T postgres pg_restore -U "$pg_user" -d "$pg_db" --clean --if-exists --no-owner < "$dir/postgres.dump"
if [ -f "$dir/phoenix.dump" ]; then
  compose exec -T postgres pg_restore -U "$pg_user" -d phoenix --clean --if-exists --no-owner --role=phoenix < "$dir/phoenix.dump" \
    || echo "warning: phoenix traces not restored (run 'make phoenix-db' first)" >&2
fi

echo "Restoring Qdrant collection '$collection'"
snapshot_file="$(find "$dir" -maxdepth 1 -name 'qdrant-*.snapshot' | head -n 1)"
[ -n "$snapshot_file" ] || { echo "error: $dir has no qdrant-*.snapshot" >&2; exit 1; }
compose exec -T qdrant mkdir -p "/qdrant/snapshots/$collection"
compose cp "$snapshot_file" "qdrant:/qdrant/snapshots/$collection/restore.snapshot"
compose run --rm --no-deps -T api python -c '
import json, sys, urllib.request
c = sys.argv[1]
body = json.dumps({"location": f"file:///qdrant/snapshots/{c}/restore.snapshot", "priority": "snapshot"}).encode()
req = urllib.request.Request(f"http://qdrant:6333/collections/{c}/snapshots/recover?wait=true",
                             data=body, method="PUT", headers={"Content-Type": "application/json"})
print(json.load(urllib.request.urlopen(req, timeout=3600))["status"])
' "$collection"
compose exec -T qdrant rm -f "/qdrant/snapshots/$collection/restore.snapshot"

echo "Restoring files"
compose run --rm --no-deps -T api sh -c 'find /data/files -mindepth 1 -delete && tar -xzf - -C /data/files' < "$dir/files.tar.gz"

echo "Starting everything"
compose up -d
echo "Restored '$name'."
