# Operator commands (spec §8). On Windows, run the scripts with Git Bash: bash scripts/<name>.sh
SHELL := bash
COMPOSE := docker compose -f deploy/docker-compose.yml

.PHONY: up down ps logs dev create-superadmin backup restore phoenix-db

up:                  ## Build and start everything
	$(COMPOSE) up -d --build

down:                ## Stop everything (data volumes are kept)
	$(COMPOSE) down

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f --tail=200

dev:                 ## Backend services only, with the API (8000) and Phoenix (6006) on localhost; no Caddy, frontend or Phoenix auth needed
	$(COMPOSE) -f deploy/docker-compose.dev.yml up -d --build postgres redis qdrant clamav phoenix api worker worker-eval

create-superadmin:   ## Create the first super admin (prompts)
	bash scripts/create-superadmin.sh

backup:              ## Back up Postgres, Qdrant and files to backups/<UTC timestamp>/
	bash scripts/backup.sh

restore:             ## Restore: make restore BACKUP=backups/<folder>
	@test -n "$(BACKUP)" || { echo "usage: make restore BACKUP=backups/<folder>"; exit 1; }
	bash scripts/restore.sh "$(BACKUP)"

phoenix-db:          ## Create Phoenix's database on an install made before Plan 8
	bash scripts/phoenix-db.sh
