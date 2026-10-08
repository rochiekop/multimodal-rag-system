#!/usr/bin/env bash
# Backup: Postgres (app + Phoenix), a Qdrant collection snapshot and the files volume, into one
# timestamped folder. deploy/.env (secrets, including RAG_SECRETS_KEY) is NOT copied.
set -euo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/lib.sh"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
dest="${1:-$ROOT/backups/$stamp}"
mkdir -p "$dest"
dest="$(native_path "$dest")"
pg_user="$(env_value POSTGRES_USER)"
pg_db="$(env_value POSTGRES_DB)"
collection="$(qdrant_collection)"

echo "Backing up to $dest"
compose exec -T postgres pg_dump -U "$pg_user" -d "$pg_db" -Fc > "$dest/postgres.dump"
if ! compose exec -T postgres pg_dump -U "$pg_user" -d phoenix -Fc > "$dest/phoenix.dump"; then
  rm -f "$dest/phoenix.dump"
  echo "warning: no phoenix database; traces not backed up (run 'make phoenix-db')" >&2
fi

# Qdrant: create a collection snapshot (from inside the network), copy it out, delete it.
snapshot="$(compose exec -T api python -c '
import json, sys, urllib.request
c = sys.argv[1]
req = urllib.request.Request(f"http://qdrant:6333/collections/{c}/snapshots?wait=true", method="POST")
print(json.load(urllib.request.urlopen(req, timeout=3600))["result"]["name"])
' "$collection" | tr -d '\r')"
delete_snapshot() {
  compose exec -T api python -c '
import sys, urllib.request
c, name = sys.argv[1], sys.argv[2]
req = urllib.request.Request(f"http://qdrant:6333/collections/{c}/snapshots/{name}", method="DELETE")
urllib.request.urlopen(req, timeout=60)
' "$collection" "$snapshot"
}
# Always remove the snapshot from Qdrant, even if copying it out fails.
if ! compose cp "qdrant:/qdrant/snapshots/$collection/$snapshot" "$dest/qdrant-$collection.snapshot"; then
  delete_snapshot || true
  echo "error: could not copy the Qdrant snapshot" >&2
  exit 1
fi
delete_snapshot

compose exec -T api tar -czf - -C /data/files . > "$dest/files.tar.gz"

{
  echo "created_utc=$stamp"
  echo "git_revision=$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  echo "alembic_revision=$(compose exec -T postgres psql -U "$pg_user" -d "$pg_db" -tAc 'select version_num from alembic_version' | tr -d '\r')"
  echo "qdrant_collection=$collection"
} > "$dest/manifest.txt"

echo "Done: $dest"
echo "Reminder: back up deploy/.env separately and securely. It holds RAG_SECRETS_KEY;"
echo "without it, API keys saved in admin Settings can't be decrypted after a restore."
