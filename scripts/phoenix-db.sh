#!/usr/bin/env bash
# Create Phoenix's own role and database on an existing Postgres volume (new installs get them
# from deploy/postgres-init). Safe to run more than once.
set -euo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/lib.sh"

pg_user="$(env_value POSTGRES_USER)"
pg_db="$(env_value POSTGRES_DB)"
phoenix_password="$(env_value PHOENIX_DB_PASSWORD)"
[ -n "$phoenix_password" ] || { echo "error: set PHOENIX_DB_PASSWORD in the env file" >&2; exit 1; }
compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$pg_user" -d "$pg_db" \
  -v pw="$phoenix_password" <<'SQL'
SELECT format('CREATE ROLE phoenix LOGIN PASSWORD %L', :'pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'phoenix')
\gexec
SELECT format('ALTER ROLE phoenix PASSWORD %L', :'pw')
\gexec
SELECT 'CREATE DATABASE phoenix OWNER phoenix'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'phoenix')
\gexec
SQL
echo "Phoenix database ready. Restart Phoenix: docker compose -f deploy/docker-compose.yml up -d phoenix"
