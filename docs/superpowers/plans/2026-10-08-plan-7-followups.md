# Plan 7 — Follow-ups for later plans

Generated from the Plan 7 execution ledger (2026-10-08). Decisions made during execution and deferred findings.

## Carry into Plan 8 (production packaging)

- `RAG_SECRETS_KEY` is required to save keys in admin Settings. Back it up with the database: without it, saved keys are unreadable.
- The logo lives in the files volume at `branding/logo`, so backups must include it.
- `NEXT_PUBLIC_PHOENIX_URL` is a frontend build-time variable.
- CSP: `img-src 'self'` covers the logo, and the audit CSV export is a same-origin download.
- The admin pages poll every 5 s while documents or eval runs are in progress.
- The extra e2e test (`frontend/e2e/admin.spec.ts`) needs the worker and an OpenAI key in CI, or is skipped there. CI must also set `E2E_USERNAME` and `E2E_PASSWORD` (a super admin) and `E2E_BASE_URL`; the defaults (`root`) rarely exist.
- The Plan 6 smoke test needs, for the e2e user, a group-accessible collection holding a **PDF** that says employees get twenty days of annual leave (it opens the page image and highlight; a Markdown document has no page image). A super admin with no group sees nothing in chat retrieval.

## Rulings made during execution

- Ruling: Settings page omits cost caps/fallback model (they live in versioned RagConfig) — spec §6.5 lists them under Settings, but versioning them with RagConfig was the Plan 3–4 design — cost if wrong: one extra navigation for admins.
- Ruling: nested <main> in app/admin/layout.tsx (plan-mandated) — fold the one-line fix (<main>→<div>) into the Task 5 dispatch — invalid landmarks otherwise — cost if wrong: none.
- Ruling: plan code that calls setState inside useEffect must be restructured (reset at open/submit, or key-remount, or derive state) because the repo's lint rule rejects it — carried into frontend-context for Tasks 7–11 — cost if wrong: none (behavior equivalent).
- Ruling: Task 8 review minor "add-to-test-set state carries across messages" can submit A's expected answer for B — fold into Task 9 dispatch: key ReviewSheet by openMessage and invalidate ["admin","eval-sets"] after add — cost if wrong: none.

## End-to-end result

Real stack: `docker compose -f deploy/docker-compose.yml up -d --build` (api, worker, worker-eval, postgres, qdrant, redis, clamav, phoenix all up), frontend via `npm run build && npm start`, super admin `e2eroot` created with `python -m app.cli create-superadmin` inside the api container.

- `npx playwright test` with `E2E_USERNAME`/`E2E_PASSWORD`: `admin.spec.ts` PASSED (28.8 s: login, create collection, upload, Ready, chunk inspector, audit shows `document.uploaded`).
- `smoke.spec.ts` (Plan 6): first run FAILED on the fresh database ("I couldn't find this in the available documents"). Causes found and verified by fixing them: (1) `e2eroot` had no group, and the collection had no group, so retrieval returned nothing. Fixed via the admin API (create group `e2e-staff`, add `e2eroot`, grant the "Seed HR" collection with password confirmation). (2) The first seed was Markdown, so the citation appeared but the test then failed at `getByRole('img', { name: /^Page 1 of / })`; a PDF was needed. Uploaded a small hand-built PDF (`leave-policy.pdf`, "Employees get twenty (20) days of annual leave per year.") and soft-deleted the Markdown one. Nothing from the seeding is committed.
- `admin.spec.ts` was not repeatable: the backend rejects identical content across collections ("Identical content was already uploaded"), so a second run failed at "1 of 1 files queued". Fixed: the spec now uploads the fixture plus a unique `Run <timestamp>` line.
- Result: `npx playwright test` with `E2E_USERNAME=e2eroot E2E_PASSWORD=…`: **2 passed** (admin.spec.ts and smoke.spec.ts), run twice in a row (15.8 s and 12.2 s).

Manual checks (Step 3.4) were scripted over HTTP through the frontend proxy (`/api` on port 3000), not clicked in a browser:

- Done: logo PNG upload, then primary color `#0f766e`. The public `/api/branding` returned the color and `logo_url`, and `/api/branding/logo` served `image/png`. NOT done: visually checking the sidebar and sign-in page.
- Done: saved the OpenAI key from `deploy/.env` with password re-entry. Key status became `source: database` with last4; that shows which source is chosen, not that it was used. `RAG_OPENAI_API_KEY` was still set in the environment, so a successful chat answer does not show the saved key was used, and that was not distinguishable here. Cleared the key: status returned to `source: environment` (the UI's "Using RAG_OPENAI_API_KEY"). The wording of the UI labels was not checked.
- Done (partly): saved a RagConfig version with a changed `rerank_top_n` (8 to 9) and activated it. NOT done: the activation dialog showing eval scores (no eval runs exist), and a rollback to a previous version (there was no previous active version; version 2 with `rerank_top_n` 8 was created and activated to restore the default).
- Done: dashboard showed 2 questions, non-zero tokens and cost, and health `database/qdrant/redis` all `ok`.
- Side effects left in the local stack: collections "E2E <timestamp>" and "Seed HR", super admin `e2eroot`, RagConfig versions 1 and 2 (v2 active), the logo and color `#0f766e`, and `RAG_SECRETS_KEY` added to `deploy/.env` (not committed).

Final verification: backend `pytest` 279 passed, `ruff check` and `ruff format --check` clean; frontend `npm test`, `lint`, `typecheck` green, `npm run build` green.

## Deferred minor findings

- Task 1: minor (deferred): no test that a rotated key yields new cached clients (wiring)
- Task 1: minor (deferred): KeyRing.refresh has no single-flight lock (concurrent DB reads at TTL expiry)
- Task 1: minor (deferred): unreadable-key warning logged every refresh
- Task 1: minor (deferred): logo file write/delete not atomic with DB commit
- Task 1: minor (deferred): no test for valid-but-disallowed image format (GIF)
- Task 2: minor (deferred): settings super_admin test covers 2 of 6 routes (generic auth test covers the rest)
- Task 2: minor (deferred): no JPEG/WebP acceptance or logo-replace test
- Task 3: minor (deferred): daily low_confidence counts all answers but total rate uses answered only (plan code)
- Task 3: minor (deferred): database health hard-coded "ok" (endpoint fails earlier if DB down)
- Task 3: minor (deferred): naive since/until read in DB session tz (frontend sends ISO with Z)
- Task 3: minor (deferred): no tests for target filters, until bound, export row cap
- Task 4: minor (deferred): PasswordDialog keeps stale password/error if parent closes it without onOpenChange
- Task 4: minor (deferred): SuperAdminOnly has no direct test (T10 models test covers the admin branch)
- Task 4: minor (deferred): layout.test replace mock not cleared between tests
- Task 5: minor (deferred): notifications page has no error state for list/mark-read
- Task 5: minor (deferred): page tests are single happy paths
- Task 6: minor (deferred): in-flight request failing after dialog close leaves stale error on reopen
- Task 6: minor (deferred): comma-expression error clearing hard to read; dialog title blanks during close animation; thin tests beyond brief
- Task 7: minor (deferred): latestVersion undefined if a document has no versions (guard)
- Task 7: minor (deferred): upload problems list keyed by filename and not cleared on collection change; thin tests (restore/access/filter/polling)
- Task 8: minor (deferred): citation chips inert in review sheet; mark-reviewed disables all rows; sheet empties during close; traceUrl untested
- Task 9: minor (deferred): no UI to delete a test set (deleteEvalSet unused); deleteCase has no confirm
- Task 9: minor (deferred): ReviewSheet key remount may cut the close animation; thin edge-case tests
- Task 10: minor (deferred): guardrails "Activate vN" button stays after activation; models note not reset after save (duplicate versions on double save); null score shows "scored —"; refetch can reset dirty forms
- Task 11: minor (deferred): no client-side logo size/type check; no success toast on logo removal; untested logo/clear-key/wrong-password paths
