# shellcheck shell=bash
# Shared helpers for the ops scripts. Source it; don't run it.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${RAG_ENV_FILE:-$ROOT/deploy/.env}"
export MSYS_NO_PATHCONV=1  # Git Bash on Windows: don't rewrite container paths like /data/files

[ -f "$ENV_FILE" ] || { echo "error: $ENV_FILE not found (copy deploy/.env.example)" >&2; exit 1; }

compose() {
  local project=()
  [ -n "${RAG_COMPOSE_PROJECT:-}" ] && project=(-p "$RAG_COMPOSE_PROJECT")
  docker compose -f "$ROOT/deploy/docker-compose.yml" --env-file "$ENV_FILE" "${project[@]}" "$@"
}

# Value of KEY in the env file, without printing anything else (quotes stripped).
env_value() {
  local line
  line="$(grep -E "^$1=" "$ENV_FILE" | tail -n 1 || true)"
  line="${line#*=}"
  line="${line%$'\r'}"
  line="${line%\"}"; line="${line#\"}"; line="${line%\'}"; line="${line#\'}"
  printf '%s' "$line"
}

qdrant_collection() {
  local name
  name="$(env_value RAG_QDRANT_COLLECTION)"
  printf '%s' "${name:-chunks}"
}
