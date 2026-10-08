# Plan 4 — Follow-ups for later plans

Generated from the Plan 4 execution ledger (2026-10-08). Decisions made during execution and deferred findings.

## Carry into Plan 5 (evaluation & review queue)

- The review queue reads `guardrail_events` (blocked, flagged, support, redirected) and `messages.low_confidence`. `classifier_unreadable` flags can be frequent if the classifier model replies in prose; watch the volume.
- Pre-flight refusals (rate limit, question length, cost caps, chat lock) write no audit row or event yet. Add a rate-limited record (one per user per window or day).
- History is paired by row adjacency. Concurrent questions in one conversation can mis-pair, so store `reply_to` on assistant messages.
- Tune `rerank_threshold`, the classifier and the judge with evaluation data. The end-to-end run behaved as expected on 9/9 steps, but that was one sample.

## Carry into Plan 7 (admin console)

- Guardrail settings live in `RagConfig.guardrails`. Edit them via `/api/admin/rag-configs` (super_admin). While cost caps are on, every model in use must have a price (enforced by a validator).
- `pii_patterns` default to an **example** `employee_number` regex `\bEMP-\d{6}\b`; set the company's real format. Admin regexes have no ReDoS guard (super_admin only), so warn in the UI.
- Notifications: `GET /api/admin/notifications`, `POST /api/admin/notifications/{id}/read`. Unlock goes through `PATCH /api/admin/users/{id}` with `unlock: true`, which clears the chat lock and resets strikes.
- When self-harm support coincides with a strike-bearing block, the `done` event carries `strikes`, `strike_limit` and `locked_until` alongside the support reply. The client should show both.

## Rulings made during execution

- Ruling: implementers use sonnet; reviewers sonnet, with opus for output/answer wiring and final reviews — cost if wrong: token cost.
- Ruling: the e2e used the existing `RAG_OPENAI_API_KEY` in `deploy/.env` without asking — cost: none.
- Ruling: the unlock test was strengthened to prove the strike reset (plan's test couldn't detect it) — cost: none.
- Ruling: the Redis client got 1 s socket timeouts, and the fail-open test uses limit=0 — cost: none.
- Ruling: classifier and judge inputs escape every `<` (the lowercase-only escape was bypassable) — cost: none.
- Ruling: OutputGuard fixes:
  - card spans are Luhn-checked group by group, so cards next to other digits are caught;
  - the PII and leak scans are incremental (the old full rescan was O(n²));
  - a value that straddles the released point has its tail redacted;
  - sources allow only whole values.

  Cost if wrong: some over-redaction of long digit runs.
- Ruling: rewrite history keeps only answered/not_found pairs, which closes the "do what I asked above" classifier bypass — cost: follow-ups after a blocked turn lose that context (intended).
- Ruling: cancelled answers get a tiktoken (`cl100k_base`) usage estimate whenever the stream reported none, even if other roles share the chat model's name — cost: estimates differ slightly from billed tokens.
- Ruling: the SSE wrapper (`sse_events`) closes the answer generator via `aclosing`; PII flags are recorded on every outcome — cost: none.
- Ruling: an unreadable classifier reply still fails open but is flagged (`classifier_unreadable`) for the review queue; model exceptions fail open with a logged warning — cost: one unclassified question per attempt, now visible.
- Ruling: `MessageOut` exposes `low_confidence` — cost: none.
- Ruling: a `RagConfig` validator requires prices for every model in use while caps are on, and usage is booked under the provider-reported model — cost: admins must add a price before switching models.
- Ruling: migration 0006 got indexes on `guardrail_events.conversation_id` and `message_id`, `usage_records.message_id`, and `(user_id, created_at)` — cost: none.
- Ruling: self-harm support no longer dodges a strike-bearing block; both events are recorded — cost: a distressed user who also attempted injection gets a strike.
- Ruling: strike-lock notifications are deduped per user per hour — cost: a re-lock within the same hour after an unlock isn't notified again.

## End-to-end result (Task 6, real stack)

answered (low_confidence false) → self-harm support (no strike) → injection blocked (strike 1) → weapons request blocked by moderation (strike 2) → jailbreak blocked (strike 3, locked 24h) → HTTP 423 → `strike_lock` admin notification → unlock → answered.

## Deferred minor findings

- **Task 1:**
  - The strike reset uses the Python clock while `created_at` uses the DB transaction time.
  - The strike check is read-then-act with no user row lock.
  - No tests for restart-after-lock, non-default window/limit, or the mark_read 404.
  - Partial moderation maps default missing categories to block.
  - `detail` can overwrite audit keys.
  - `app/models.py` `__all__` isn't in order.
- **Task 2:**
  - Commit-on-refusal is untested.
  - A success-path cost alert is rolled back if conversation creation fails (re-fires next time).
  - The conftest ping client is never closed.
  - The lifespan close order lets a Redis failure skip the Qdrant close.
- **Task 3:**
  - The support-vs-block precedence is only partly tested.
  - `on_usage` isn't asserted.
  - The moderation map is only partly tested.
  - There's a type-ignore on `settings.moderation.get`.
- **Task 4:**
  - An overlapping match from a second pattern is dropped, not merged.
  - The leak check is inert for system prompts under 8 words.
  - Judge `on_usage` errors propagate.
  - The judge's sources block is only lowercase-escaped (Plan 3 `format_sources`).
  - Custom PII values over 256 characters can show a prefix released before the match is known.
  - Card spans in sources vs answer can differ (over-redaction, not a leak).
  - A rare longest-span shift is bounded by the holdback.
  - Missing tests: IBAN, overlap, judge exceptions.
- **Task 5:**
  - Cancelled content isn't citation-cleaned.
  - The one-usage-record check covers only some outcomes.
  - `sse_events` can raise "ignored GeneratorExit" if the save fails during a disconnect close.
  - The prompt estimate over-counts when the provider fails before the first chunk.
  - `_history` loads the whole conversation.
- **Final review:**
  - The system-prompt leak check is bypassable by paraphrase or translation, and can trip on quoted prompt sentences (document it).
  - The fixed-window rate limiter allows a 2× burst at window boundaries.
  - `price_key` maps variants under any priced prefix.
  - `ix_usage_records_user_id` is redundant next to the composite index.
