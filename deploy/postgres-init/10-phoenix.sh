#!/bin/sh
# Runs once, when the Postgres volume is first created: Phoenix gets its own role and database
# (traces hold questions and document text; they don't belong in the app database).
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<EOSQL
CREATE ROLE phoenix LOGIN PASSWORD '${PHOENIX_DB_PASSWORD}';
CREATE DATABASE phoenix OWNER phoenix;
EOSQL
