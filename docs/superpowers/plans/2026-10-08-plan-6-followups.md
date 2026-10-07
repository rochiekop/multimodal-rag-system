# Plan 6 — Follow-ups for later plans

Generated from the Plan 6 execution ledger (2026-10-08). Decisions made during execution and deferred findings.

## Carry into Plan 7 (admin console)

- Reuse the foundation:
  - `lib/api.ts`: `apiFetch` adds the CSRF header and `ApiError`.
  - `components/providers.tsx`: React Query, with a global 401 handler.
  - The `Field`/react-hook-form/zod form patterns from `components/auth`.
  - `navigateTo` for full navigations.
- An admin link in the sidebar user menu (role ≥ admin) and the `/admin` route tree are not built yet.
- Branding (`NEXT_PUBLIC_APP_NAME` today) moves to admin Settings (spec §6.8).

## Carry into Plan 8 (production packaging)

- **Frontend container + Caddy:**
  - Caddy routes `/api` straight to FastAPI and everything else to Next.
  - `BACKEND_URL` rewrites are fixed at **build time**. Keep `compress: false` in Next and let Caddy compress, but never buffer `text/event-stream`. SSE was verified to stream through the Next rewrite (token events about 60–100 ms apart).
- **CSP and security headers:** `img-src 'self' data:` (Markdown images are already rendered as links), `frame-ancestors 'none'`, `default-src 'self'`.
- **Cookies on plain HTTP:**
  - `RAG_ENV=prod` makes the session cookie `Secure`. On a plain-HTTP intranet host other than localhost the browser drops it and users loop at `/login`.
  - Document `RAG_SESSION_COOKIE_SECURE=false` for that case, or require HTTPS (Caddy).
- **CI:**
  - frontend `npm ci` (`.npmrc` has `legacy-peer-deps=true`, needed because `@vitejs/plugin-react` 6 and shadcn's Babel 7 peer ranges conflict), `npm run lint`, `typecheck`, `test`, `build`;
  - the Playwright smoke test (`npm run e2e` with `E2E_USERNAME`/`E2E_PASSWORD`/`E2E_BASE_URL`) against a seeded stack.
- Replace the CLI-boilerplate `frontend/README.md` with real setup notes.

## Rulings made during execution

- Ruling: the session uses a backend httpOnly `SameSite=Strict` cookie (`rag_session`, Path=/, Secure in prod) with `X-CSRF-Protection: 1` on cookie-authenticated writes. There are separate browser endpoints `/api/auth/session` (POST, DELETE) and `/api/auth/session/password`. Bearer is unchanged — cost: three small routes.
- Ruling: a clean `npm ci` needs a committed `frontend/.npmrc` (`legacy-peer-deps=true`) — cost: npm peer checks are relaxed for this project.
- Ruling: `handleUnauthorized` clears the cookie and only navigates when the user isn't already on `/login`, which prevents reload loops — cost: none.
- Ruling: the SSE parser normalises CR/CRLF on the buffer, cancels the stream on early exit, and treats malformed data as `bad_stream`. `vite-tsconfig-paths` was dropped for Vitest's native tsconfig paths — cost: none.
- Ruling: the `requireCurrent` flag in the plan's Task 3 interface was dropped. Sign-out lives in the user menu (Task 4) and on `/change-password` — cost: none.
- Ruling: `safeNext` parses against a fixed origin and rejects backslashes and control characters (an open-redirect hole in the plan's code) — cost: none.
- Ruling: sign-out clears the query cache and does a full navigation, and the app layout waits for `me` before rendering. A client-side `router.push` (the implementer's change) had left the previous user's data in memory — cost: none.
- Ruling: the chat aborts its stream on unmount and moves to `/app/c/<id>` only after the first answer. Viewed conversations are invalidated, not removed, so a later visit loads fresh — cost: leaving mid-answer cancels it (saved as "Stopped").
- Ruling (final review):
  - `["me"]` is set after a forced password change, so the user isn't bounced back to the change page.
  - Markdown images render as links, never `<img>` (closes an exfiltration channel).
  - The login page probes `/me` and skips straight in when a session already exists, so the Strict cookie doesn't force a re-login from outside links.
  - The app layout shows an error with a Retry button when `/me` fails.
  - The collection choice survives a new chat's move to its URL.
  - A stream that ends without a final event is marked stopped.

  Cost if wrong: images in answers show as links.

## End-to-end result (Task 6, real stack)

Playwright run: 1 passed (24 s). It signed in, asked a question, saw a cited answer with a "Source 1" badge, opened the page image with its highlight, and gave 👍 feedback. A curl run through `localhost:3000` confirmed SSE streams progressively through the Next rewrite.

## Deferred minor findings

- **Backend (Task 1):**
  - The CSRF check uses an unsafe-method list; a safe-method allowlist is preferable (not exploitable today, since Starlette returns 405 first).
  - The legacy `/api/auth/change-password` accepts cookie auth and returns a raw token (needs the current password).
  - The `cookie_secure` true branch, PATCH/DELETE CSRF and wrong-header-value cases are untested.
  - `_authenticate` is annotated `SessionDep`, and the password-change error mapping is duplicated.
- **Task 2:**
  - `proxy.ts` drops the query string from `next=`.
  - Lone-CR-only SSE servers delay their last event.
- **Task 3:**
  - Inputs lack `aria-invalid`/`aria-describedby`.
  - An exception thrown from `onDone` shows "Could not reach the server".
- **Task 4:**
  - Search has no `keepPreviousData`, so the skeleton flickers.
  - The AlertDialog closes on a failed delete.
  - An empty `full_name` shows an ellipsis.
- **Task 5:**
  - `aria-live` covers the whole message list.
  - The spinner SVG lacks `role="img"`.
  - 👍 isn't disabled while pending.
  - A collections query error shows as "no collections".
  - The highlight is re-measured only on window resize.
  - No viewer/highlight tests.
- **Final:**
  - ChatView shows "isn't available" if a background refetch errors while data exists (check `!data` first).
  - An unstarted "new" collection choice survives leaving a new chat mid-first-answer.
  - "Can't reach the server" may flash before a 401 redirect.
  - `@types/node` is ^20 while Node 24 is used.
