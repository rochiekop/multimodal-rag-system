# Multimodal RAG system

An enterprise knowledge assistant. Staff upload documents (PDF, Office files, Markdown, images); the system scans them for malware, extracts text, tables and figures, indexes them with hybrid dense and sparse retrieval, and answers questions with citations that open the exact source page with the cited passage highlighted. Access is controlled per collection through groups, answers stream token by token, every sensitive action is audited, and an admin console covers documents, users and groups, guardrails, evaluation runs, settings and cost. Traces of every LLM call go to Phoenix. The full design is in `docs/superpowers/specs/2026-10-04-multimodal-rag-v1-design.md`.

## Requirements

- Docker with Compose 2.17 or later.
- Medium install: 4 vCPU and 16 GB RAM. Large install: 8 vCPU, 32 GB RAM and 500 GB SSD (spec section 8.3).
- An OpenAI API key (embeddings, figure descriptions, moderation, answers).
- A DNS name pointing at the host with ports 80 and 443 open, if you want a public Let's Encrypt certificate.

## Install

1. Create your settings file:

   ```bash
   cp deploy/.env.example deploy/.env
   ```

2. Fill in `deploy/.env`. Each secret has its generating command in the file: `RAG_JWT_SECRET` (`secrets.token_urlsafe`), `RAG_SECRETS_KEY` (a Fernet key), and `POSTGRES_PASSWORD` and `PHOENIX_DB_PASSWORD` (letters and digits only, they are embedded in URLs). Set `RAG_OPENAI_API_KEY`. Create the Phoenix basic-auth hash with `docker run --rm caddy:2.10.2-alpine caddy hash-password --plaintext 'your-password'` and keep the single quotes in the file.

   `RAG_DOMAIN` has three modes:
   - A public DNS name: Caddy obtains and renews a Let's Encrypt certificate automatically.
   - `localhost` or an intranet name: Caddy's internal CA issues the certificate; browsers warn until it is trusted.
   - `:80`: plain HTTP. Also set `RAG_SESSION_COOKIE_SECURE=false`, otherwise the browser will not send the session cookie. Use this only behind another TLS terminator or on a trusted network.

   `HTTP_PORT` and `HTTPS_PORT` change the published ports (defaults 80 and 443).

3. Start the stack:

   ```bash
   docker compose -f deploy/docker-compose.yml up -d    # or: make up
   ```

   The first build downloads models and takes several minutes; ClamAV can take up to 5 minutes to become healthy.

4. Create the first super admin:

   ```bash
   make create-superadmin           # Windows: bash scripts/create-superadmin.sh
   ```

   The script prompts for username, full name and password. For automation set `RAG_SUPERADMIN_USERNAME`, `RAG_SUPERADMIN_FULL_NAME` and `RAG_SUPERADMIN_PASSWORD`.

5. Open `https://<domain>` and sign in.

## Upgrade

```bash
git pull
docker compose -f deploy/docker-compose.yml up -d --build
```

Database migrations run automatically when the API starts. Installs made before Plan 8 have no Phoenix database yet: run `make phoenix-db` once, then `up -d`.

## Backup and restore

```bash
make backup                              # writes backups/<UTC timestamp>/
make restore BACKUP=backups/<folder>
```

A backup holds a Postgres dump, a Qdrant snapshot of the chunk collection and an archive of the files volume (originals, page images, logo). Restore replaces the current data; scripts ask for confirmation (`--yes` skips it).

Schedule it with cron, for example `0 2 * * * cd /opt/rag && make backup`, and copy the folders off the host.

**Back up `deploy/.env` separately.** It is not part of the backup, and `RAG_SECRETS_KEY` is needed to read API keys saved in admin Settings. Without it they must be entered again.

## Operations

- Logs: `make logs` or `docker compose -f deploy/docker-compose.yml logs -f <service>`. Backend logs are JSON and carry a request ID; Caddy overwrites any client-supplied `X-Request-ID`, so audit rows can be trusted.
- Phoenix (LLM traces): `https://<domain>/phoenix`, behind basic auth (`PHOENIX_BASIC_AUTH_USER` / `PHOENIX_BASIC_AUTH_HASH`).
- Health: `docker compose -f deploy/docker-compose.yml ps` (every service should be `healthy` or `running`); `GET /api/health` for the API; the admin dashboard shows database, Qdrant and Redis.
- Limits: 100 MB per file and 500 MB per upload request; other API requests are capped at 10 MB.

## Development

- `make dev` starts only the backend services with the API on port 8000 and Phoenix on 6006 (no Caddy, no frontend, no basic auth).
- Frontend: in `frontend/`, `npm run dev`. See `frontend/README.md`.
- Backend tests: `cd backend && uv run pytest` (needs Docker for testcontainers). Also `uv run ruff check .`, `uv run ruff format --check .` and `uv run mypy`.
- Frontend checks: `npm test`, `npm run lint`, `npm run typecheck`, `npm run build`.
- End-to-end tests: `cd frontend && E2E_BASE_URL=... E2E_USERNAME=... E2E_PASSWORD=... npm run e2e` against a running stack with a super admin. The global setup seeds a group, a collection and a leave-policy PDF. For a self-signed certificate add `E2E_IGNORE_HTTPS_ERRORS=1`.

## CI

GitHub Actions runs on every push: backend ruff, mypy and pytest; frontend lint, typecheck, tests and build; and a build of the backend and frontend images. The e2e tests are manual because they need a running stack and an OpenAI key.

## Security notes

- Everything is served over HTTPS by Caddy, with HSTS, a strict Content-Security-Policy, `X-Frame-Options: DENY` and no `Server` header.
- State-changing API calls need the `X-CSRF-Protection` header, and the session cookie is HTTP-only.
- Phoenix is reachable only through Caddy and only with basic auth; its port is not published.
- Destructive admin actions (deleting documents or collections, changing access, saving API keys) require the admin to re-enter their password.
- Uploads are scanned by ClamAV before processing.

## Repository layout

- `backend/`: FastAPI API, Celery workers (ingestion and evaluation), migrations and tests.
- `frontend/`: Next.js app (chat and admin console) and the Playwright e2e tests.
- `deploy/`: `docker-compose.yml`, the dev override, the `Caddyfile`, Postgres init scripts and `.env.example`.
- `scripts/`: backup, restore, super admin and Phoenix database helpers (Git Bash friendly).
- `docs/superpowers/`: the design spec, the implementation plans and their follow-ups.

## Troubleshooting

- The stack looks stuck on first start: ClamAV downloads its signatures and can take up to 5 minutes to become healthy; the workers wait for it.
- The browser warns about the certificate: with `localhost` or an intranet name Caddy uses its own CA. Trust it or use a public DNS name.
- Login works but you are signed out at once on plain HTTP: set `RAG_SESSION_COOKIE_SECURE=false` (only with `RAG_DOMAIN=:80`).
- Saved API keys show as unreadable: `RAG_SECRETS_KEY` changed. Restore the original from your separate `deploy/.env` backup, or enter the keys again in Settings.
- Docker needs several GB of free disk for the first build (the backend image bundles models).
