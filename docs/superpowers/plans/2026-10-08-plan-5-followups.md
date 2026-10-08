# Plan 5 — Follow-ups for later plans

Generated from the Plan 5 execution ledger (2026-10-08). Decisions made during execution and deferred findings.

## Carry into Plan 7 (admin console)

- **Eval sets:** `/api/admin/eval-sets` (UI label "test sets").
  - CSV columns: `question` (required), `expected_answer`, `expected_sources` (`<doc_id>[:page];…`), `collections` (names, `;`), `groups` (names, `;`), `unanswerable`. Header names are case-insensitive.
  - Bad rows come back as `{row, message}` with line numbers.
- **Runs:**
  - `POST /api/admin/eval-runs` returns 202. Poll `GET /api/admin/eval-runs/{id}`.
  - `GET /api/admin/eval-runs/compare?a=&b=` gives per-question regressions with reasons.
  - Summary keys: `metrics`, `idk_accuracy` (unanswerable cases only), `answered_rate` (answerable cases), `latency_p50_ms`, `latency_p95_ms`, `cost_per_question_usd`, `errors`, `score`.
- **`latest_eval` on RagConfig versions** may come from a different eval set than the active version's. Show `eval_set_id` next to the score, or filter by set.
- **Review queue:** `/api/admin/review-queue` (kinds `feedback`, `low_confidence`, `guardrail`), the message detail view, mark-reviewed, and add-to-eval-set. Every list and detail view is audited (`review.queue_viewed` records the items shown).
- **Shared review state:** one `reviewed_at` per message, so reviewing a 👎 also clears that message's low-confidence entry.

## Carry into Plan 8 (production packaging)

- **Eval worker service:** eval runs execute on the separate `worker-eval` compose service (`-Q evaluation`, concurrency 1), and ingestion stays on `worker`.
- **Stale runs:** runs are claimed once (`queued` → `running`) and acked early. A worker crash mid-run leaves the run `running` forever, so add a reaper that times out stale `running` runs.
- **Dependency pins:**
  - `ragas==0.4.3` needs `langchain-community==0.4.1`, because later community releases removed `chat_models.vertexai`.
  - `[tool.uv] override-dependencies = ["jiter>=0.17.0", "openai>=3.24.0,<4"]` keeps the production OpenAI SDK current despite instructor's `jiter<0.15`.
  - Re-check both on every upgrade.

## Rulings made during execution

- Ruling: implementers sonnet; reviewers sonnet, opus for the runner/runs tasks and final reviews — cost if wrong: token cost.
- Ruling: the e2e used the existing `RAG_OPENAI_API_KEY` — cost: none.
- Ruling: CSV import reports rows with extra columns as errors (it used to 500), gives readable `loc: msg` row errors, and checks only expected-source documents per row — cost: none.
- Ruling: mark-reviewed validates the target kind (404 otherwise); one `reviewed_at` is shared per message (documented) — cost: reviewing for one reason clears both entries.
- Ruling: a uv override keeps openai 3.26 / jiter 0.17 after ragas pulled them down to 3.3 / 0.14 — cost if wrong: an instructor incompatibility (the e2e Ragas scoring worked).
- Ruling: Ragas metric values that are None or non-finite become None per metric; `hit_rate` is None on errors — cost: none.
- Ruling: the plan's compare test assumed the wrong idk arithmetic, so it was replaced by a score/answered-rate assertion — cost: none.
- Ruling: the plan's e2e threshold of 0.999 didn't refuse the sample question (rerank score 0.9998), so the e2e added a run at 1.0, which exercised the regression path — cost: none.
- Ruling: "I don't know" accuracy is measured only on unanswerable cases (spec §7.1). A new `answered` rate on answerable cases catches guardrail-blocked or refused answers, and compare flags "outcome answered → X" — cost: scores aren't comparable with runs made before this change.
- Ruling: eval runs are claimed atomically, acked early, results are unique per (run, case), and a load failure marks the run failed — cost: crashed runs stay `running` (see Plan 8).
- Ruling: there is a separate `worker-eval` service — cost: one more container.
- Ruling: the `review.queue_viewed` audit records the items shown (kind, id, message id, owner) — cost: larger audit rows.

## End-to-end result (Task 5, real stack)

- **CSV import:** 2 cases created.
- **Run A:** all Ragas metrics came back as numbers, and both cases were correct on "I don't know".
- **Strict config (threshold 1.0):** the leave question became `not_found`. Compare flagged it as regressed, and `latest_eval` showed the score.
- **Review queue:** the 👎 item, its detail view and add-to-set all worked, and `review.queue_viewed`, `review.message_viewed` and `review.added_to_eval_set` were audited.
- **Phoenix:** the `eval.case` spans carry `eval.run_id`.

## Deferred minor findings

- **Task 1:**
  - Multi-line quoted rows report their end line.
  - Two concurrent creates with the same name return a 500.
  - `_set_out` is untyped.
  - No tests for 413/422/oversize files, the row limit, or case 404s.
- **Task 2:**
  - Pagination and merge order are untested.
  - The listing makes N+1 queries, and large offsets waste work (consider capping offset at ~1000).
  - Asserts in the detail and add-to-set paths.
  - Pre-flight dedupe is tested for one user and one check only.
- **Task 3:**
  - `answer_once` skips the tiktoken generation estimate.
  - `not_found` hit rate uses the closest 3 cards.
  - The `eval.case` span doesn't record exceptions.
  - No span-attribute test.
- **Task 4:**
  - `score` isn't comparable across runs with different metric sets (add per-metric `n`).
  - `latest_scores` loads every completed run.
  - Compare doesn't check that both runs share an eval set, and drops unmatched cases.
  - Missing run-as groups are dropped silently.
  - The 503 path and the API-level `latest_eval` attachment are untested.
- **Final review:**
  - Message detail opens any assistant message (it is audited).
  - Case edits and CSV imports aren't audited.
  - Deleting a case mid-run fails the run.
  - Review-derived cases outlive conversation deletion (document this).
  - `_fail` can mark a run failed after a transient DB error while another worker holds it.
  - The raw-outcome regression reason adds noise for uncited answers.
  - The unique-constraint name deviates from the naming convention (model and migration agree).
