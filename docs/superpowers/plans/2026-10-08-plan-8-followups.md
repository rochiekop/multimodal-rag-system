# Plan 8 — Follow-ups for later plans

Generated from the Plan 8 execution ledger and the fresh-install verification (2026-10-08).

## Rulings made during execution

- Ruling: fix the BM25 offline load now (sparse.py loads from the cached snapshot path when present) plus restore Dockerfile line continuations and log /api/health access at DEBUG — an HF outage would otherwise break chat and ingestion in production — cost if wrong: one small fix round.
- Ruling: fold two Task 4 minors into Task 5 dispatch — `make dev` starts only backend services (no caddy/frontend, no 80/443 or basic-auth needed), and the Caddy @upload matcher adds `method POST` (spec says 500 MB on POST) — cost if wrong: none.
- Ruling: fix lib.sh ROOT with `pwd -W` fallback `pwd`, and convert user-supplied absolute paths with `cygpath -m` when available — plan-mandated code was wrong for Windows; constraint "runnable from Git Bash" is binding — cost if wrong: none on Linux (pwd -W absent → pwd).
- Ruling (Task 7): Phoenix is proxied with `handle_path /phoenix*` (prefix stripped) while `PHOENIX_HOST_ROOT_PATH=/phoenix` stays set. With plain `handle` the HTML loaded but every asset under `/phoenix/assets/` returned the SPA page instead of the file. Phoenix's OTLP endpoint stays `http://phoenix:6006/v1/traces` (the `/phoenix/v1/traces` path answers 405); 112 traces arrived in the `multimodal-rag` project.

## End-to-end verification

Isolated stack: compose project `rag-verify`, own env file, ports 8080/8443, `RAG_DOMAIN=localhost`. The dev project `multimodal-rag` and its volumes were not touched.

- PASSED: fresh `up -d --build --wait`; every service healthy or running (caddy, phoenix and the workers have no healthcheck and showed running).
- PASSED: super admin created with `scripts/create-superadmin.sh` (spec §1.2 criterion 6).
- PASSED: `GET /login` 200 with Content-Security-Policy, X-Frame-Options DENY, X-Content-Type-Options and Strict-Transport-Security, and no Server header.
- PASSED: `GET /api/health` 200. A forged `X-Request-ID: forged` is replaced by a UUID.
- PASSED after fix: `/phoenix/` 401 without auth, 200 with basic auth; its scripts and styles load (JS served as text/javascript) once `handle_path` is used. Plain `handle` failed.
- PASSED: 11 MB POST to `/api/auth/session` returns 413.
- PASSED: `http://localhost:8080/` answers 308 to `https://localhost/` (port 443, not 8443; expected with non-default ports, harmless on a standard install).
- PASSED: e2e against `https://localhost:8443`: 2 passed, with the new global setup seeding data first.
- PASSED: streaming through Caddy. A long answer produced 114 `event: token` lines over about 13.6 s before `done`; the response had no `Content-Encoding`. A one-sentence answer arrives as a single token event.
- NOT FULLY PASSED: trace link. `GET /phoenix/redirects/traces/<trace_id>` returns 200 but it is the SPA fallback page (an unknown id returns the same), so Phoenix 20.19.0 has no such route and the link opens the Phoenix home, not the trace. Traces do reach Phoenix.
- PASSED: backup, `down -v` of the rag-verify project, `up -d --wait`, restore `--yes`: the stack became healthy, login with the old password worked, chat cited `leave-policy.pdf`, `GET /api/documents/<id>/pages/1` returned 200 image/png, Phoenix answered 200, and e2e passed again (2 passed).
- NOT CHECKED: Let's Encrypt (public DNS name) and `:80` plain-HTTP modes; the CI workflow run on GitHub; HSTS and CSP behaviour in a real browser beyond what the e2e exercises; restore onto a different host.

### Environment incident (not a product defect)

The first image build filled the C: drive (Docker Desktop's disk image grew to 58 GB with about 40 MB free). The Docker engine returned HTTP 500 and then would not start; recovery needed freeing a few GB of caches and restarting Docker Desktop and WSL, which briefly stopped the dev containers (they came back by themselves). Keep several GB free before a first build; the backend image is about 1.4 GB and the BuildKit cache several times that.

## Deferred minor findings

- Task 1: minor (deferred): cp -a copies stale models from the cache mount; client-disconnect logged as status 500; flaky test_chat_limits::test_rate_limit_per_minute under load
- Task 1: minor (deferred): test_bm25_path_resolution lives in test_logging.py
- Task 2: minor (deferred): evaluation/service._missing model typed Any; long ignore line in limits.py
- Task 3: minor (deferred): README forward references (make dev, dev override, e2e global setup) — resolved by Tasks 4/5/7
- Task 4: minor (deferred): HSTS also sent in localhost mode
- Task 5: minor (deferred): phoenix password in psql args; env_value vs compose .env parsing differences; stale redis jobs after restore
- Task 5: minor (deferred): superadmin winpty hint fires on any failure; failed backup leaves a partial folder
- Task 6: minor (deferred): push+pull_request double-runs PR branches; consider Dependabot for actions; workflow not yet executed (needs push)
- Trace deep link: Phoenix 20.19.0 has no `/redirects/traces/<id>` route, so the console's trace link only opens Phoenix. Either link to `/phoenix/projects` or show the trace ID only.
- Phoenix has no healthcheck, so the API can start before it is ready and a first OTLP export may fail (traces are best effort).
- `http://host:8080` redirects to the default HTTPS port; set the redirect target with a site address that includes the port if non-default ports are used in production.

## Remaining work after v1

- Pinned image digests and a private registry for release builds.
- Scheduled off-host backups (object storage), with a restore drill in CI.
- E2E in CI with a secret OpenAI key and a throwaway stack.
- Phoenix and worker healthchecks; make `api` wait for Phoenix being healthy.
- Read-only root filesystems and non-root users for all services.
