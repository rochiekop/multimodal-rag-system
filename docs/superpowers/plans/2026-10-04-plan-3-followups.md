# Plan 3 — Follow-ups for later plans

Generated from the Plan 3 execution ledger (2026-10-07). Decisions made during execution and deferred findings.

## MUST carry into Plan 4 (guardrails & abuse protection)

- **Cancelled answers are not metered.** If the client disconnects mid-stream, `answer()` is closed before its final save, so no assistant message, token count or cost is stored. Cost caps (spec §5.3) read stored token counts. Fix: `try/finally` with a shielded save (anyio `CancelScope(shield=True)`) that writes `outcome="cancelled"` with partial content and usage.
- Use the collection `sensitive` flag (already on every chunk payload) in the exfiltration guardrail (spec §5.1).

## MUST carry into Plan 8 (production packaging)

- The Phoenix UI has no login and traces contain questions and chunk text from restricted documents. Keep it on localhost and put it behind Caddy auth.
- Phoenix uses the app's Postgres superuser and database. Give it a dedicated role or database.
- `X-Request-ID` from the client is trusted and written into audit rows. Have Caddy set or overwrite it.
- Uvicorn's own loggers (`uvicorn`, `uvicorn.access`) are not JSON-formatted and carry no request ID. Unhandled 500s likely lack the `x-request-id` header.

## Rulings made during execution

- Ruling: implementers use sonnet (Plan 2 precedent) — cost if wrong: higher token cost.
- Ruling: Task 6 end-to-end run used the existing `RAG_OPENAI_API_KEY` in `deploy/.env` without asking, because it was already set — cost: none.
- Ruling: Task 5's SSE wrapper catches exceptions escaping `answer()` and emits a final `error` event (`answer_failed`), so the client always gets a terminating event (spec §5.3 "clear error message") — cost if wrong: a few lines beyond the plan text.
- Ruling: Task 6's checks for the `chat.answer` span and its LangChain child spans in the Phoenix UI, and for the api's JSON log lines, were accepted without being seen. Evidence: the e2e `done` event carried a non-null trace ID, Phoenix showed the project with 15 traces, the span name is pinned by `test_tracing`, and the JSON format is unit-tested — cost if wrong: child spans missing until someone opens the Phoenix UI.
- Ruling: the final review's "disconnect saves nothing" finding was plan-accepted for v1 and is carried to Plan 4 (above) — cost if wrong: unmetered tokens on cancelled answers until then.
- Ruling: the final review's missing spec §9 tests (collection-group revocation, user removed from group) were added before merge.

## End-to-end result (Task 6, real stack)

- An in-scope question was answered with `[1]` cited to page 1 with a bbox; top rerank score 0.9998.
- An off-topic question returned `not_found`; top score 0.0.
- The default `rerank_threshold` of 0.1 separated the two cleanly on this sample. Revisit it with Plan 5 evaluation data.

## Deferred minor findings

- Task 1: a 500 from an unhandled exception likely lacks `x-request-id`; `configure_logging`/`log_level` untested; the audit request-id test reads the latest row by id.
- Task 2: concurrent activations or creates can return a 500 (the DB invariant still holds); re-activating the active version rewrites `activated_at` and the audit entry; no tests for activate 404, non-super_admin activate/GET, or the DB one-active constraint; `get_active` raises if a stored config stops validating after a schema change.
- Task 3: the Postgres collection re-check has no test that fails without it (documents can't move collections today); the `payload_groups` test helper is unused; a malformed Qdrant payload raises a 500 in `retrieve`; no RED evidence was recorded (the reviewer confirmed the security tests fail when their check is removed).
- Task 4: the citation regex strips out-of-range bracketed numbers such as `[2024]`, and doesn't touch ranges like `[1-3]`; `</SOURCE` in other casing is not escaped; history keeps user questions whose answer errored; an OpenTelemetry span held across `yield`s may log "Failed to detach context"; tests don't cover a mid-stream error, non-zero cost, an active config version, or the 3-source cap; `cost_usd` is a float.
- Task 5: the wrapper error test asserts only the code; a failure before the first `meta` event leaves an empty conversation; a whitespace-only `q` acts as a wildcard.
- Task 6: no test for the enabled or idempotent path of `setup_tracing`; Phoenix has no healthcheck; the Phoenix DB URL variables lack `:?` guards; the worker receives `RAG_PHOENIX_ENDPOINT` but never calls `setup_tracing`.
- Final review: page images always come from the current version, so old citations show the new page after a version swap; the user-group test is guarded only by the empty-groups early return.
