#!/usr/bin/env bash
# Create the first super admin. Prompts for the password unless RAG_SUPERADMIN_PASSWORD is set.
set -euo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/lib.sh"

username="${RAG_SUPERADMIN_USERNAME:-}"
full_name="${RAG_SUPERADMIN_FULL_NAME:-}"
[ -n "$username" ] || read -r -p "Username: " username
[ -n "$full_name" ] || read -r -p "Full name: " full_name
if [ -n "${RAG_SUPERADMIN_PASSWORD:-}" ]; then
  compose exec -T -e RAG_SUPERADMIN_PASSWORD api \
    python -m app.cli create-superadmin --username "$username" --full-name "$full_name"
else
  compose exec api python -m app.cli create-superadmin --username "$username" --full-name "$full_name" || {
    echo "hint: on Git Bash/mintty an interactive exec needs 'winpty bash scripts/create-superadmin.sh', or set RAG_SUPERADMIN_PASSWORD" >&2
    exit 1
  }
fi
