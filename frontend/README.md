# Frontend

The Next.js (App Router, React 19) web app for the multimodal RAG system. It has two parts:

- the user app at `/app`: chat with citations over the collections a user can access;
- the admin console at `/admin`: users, groups, collections, documents, evaluations and settings.

Everything talks to the FastAPI backend through `/api`.

## Development

1. Install dependencies with `npm install`. The `.npmrc` sets `legacy-peer-deps=true`, which is
   needed because the peer ranges of `@vitejs/plugin-react` 6 and shadcn's Babel 7 conflict.
2. Start the backend stack from the repo root with the dev override:
   `docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml up -d`
   (a `make dev` target wraps this).
3. Run `npm run dev`. It proxies `/api` to `BACKEND_URL` (default `http://127.0.0.1:8000`).

## Checks

```bash
npm run lint
npm run typecheck
npm test
npm run build
```

## End-to-end tests

`npm run e2e` runs Playwright against a running stack. Set:

- `E2E_BASE_URL`: where the app is served;
- `E2E_USERNAME` and `E2E_PASSWORD`: a super admin account.

The global setup seeds a group, a collection and a PDF. The tests need the worker running and a
real OpenAI key in the backend.

## Production

`deploy/docker-compose.yml` builds this app (the `frontend` service) from `frontend/Dockerfile`:
a multi-stage build with Next.js standalone output, running as a non-root user on port 3000, with
a health check on `/login`.

Build args:

- `NEXT_PUBLIC_APP_NAME`
- `NEXT_PUBLIC_PHOENIX_URL`
- `BACKEND_URL`

They are fixed at build time, so rebuild the image after changing them. Branding (name, color,
logo) is set at runtime in admin Settings. In production Caddy routes `/api` straight to the
backend.
