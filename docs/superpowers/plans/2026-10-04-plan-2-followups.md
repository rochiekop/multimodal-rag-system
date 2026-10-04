# Plan 2 — Follow-ups for later plans

Generated from the Plan 2 execution ledger (2026-10-04). Decisions made during execution and deferred findings.

## MUST carry into Plan 3 (retrieval)

- For every search result, re-check in Postgres that the document is not deleted and the user's groups intersect its effective access groups (Qdrant payload sync happens after DB commits and can briefly lag or fail).
- Only accept chunks whose `version_id` equals the document's `current_version_id` (covers leftover points from failed post-commit cleanup).

## Rulings made during execution

- | T5 self | md heading levels assumed (## → level 1, ### → level 2) — unverified | Ruling: implementer verifies against real Docling output; adjust heading-level arithmetic (not the expected test values) if Docling levels differ — expected paths are the spec behavior — cost if wrong: one function |
- | T7 self | e2e needs RAG_OPENAI_API_KEY from user | Ruling: controller asks user only when Task 7 reaches the e2e step — security-sensitive secret — cost: pause at T7 |
- Ruling: implementers from Task 2 on use sonnet, not haiku — haiku took 44 turns/25 min on T1 and produced no real RED run (TDD evidence missing) — cost if wrong: higher per-task token cost
- Task 2: Ruling: plan-mandated Important #1 (scan_bytes leaks raw OSError/TimeoutError, finally can mask it) — fix: convert connection/IO failures to ScanError, make close tolerant — spec §3.3 needs reliable scan outcomes; cheap — cost if wrong: small code churn
- Task 2: Ruling: plan-mandated Important #2 (ensure_collection: payload indexes skipped forever after partial failure; concurrent create race) — fix: always (idempotently) ensure payload indexes, tolerate "already exists" on create — API and worker both bootstrap the collection — cost if wrong: small code churn
- Task 3: Ruling: DocumentServiceError(message) with class-level code (brief code) over Interfaces text '(code, message)' — same pattern as Plan 1 UserServiceError — cost if wrong: none
- Task 3: Ruling: Important #1 (Qdrant payload sync after commit can fail open on access revocation) — parked as the plan's documented known gap: Plan 3 retrieval MUST re-check document access + deleted status in Postgres for every result — cost if wrong: if Plan 3 forgets, revoked users could read chunks; carry into Plan 3 spec/plan
- Task 3: Ruling: Important #2 (core access intersection + wrong-password + 404/422 untested) — enters fix loop; tests only — cost if wrong: small
- Task 4: Ruling: duplicate detection stays global across collections — spec §3.2 'identical content already exists → duplicate' — cost if wrong: same file can't live in two collections with different access (admin must use groups instead); revisit if user wants per-collection
- Task 4: Ruling: Important #1 (enqueue deferred to end of upload loop → committed versions can stay queued forever on a later failure) — plan-mandated; fix: enqueue each version right after its commit — cost if wrong: none
- Task 4: Ruling: Important #2 (request body spooled before size check; no file-count cap) — parked to Plan 8: Caddy request_body max_size + Starlette multipart limits; spooling goes to disk not RAM — cost if wrong: disk-filling uploads until Plan 8
- Task 4: Ruling: Important #3 (zip guard trusts declared sizes) — parked: real decompression happens in the worker (Docling); add worker memory/time limits in Plan 8 — cost if wrong: a crafted docx can exhaust worker memory until then
- Task 4: Ruling: Important #4 (weak tests on security paths) — enters fix loop
- Task 5: Ruling: table Markdown cells space-collapsed (re.sub " {2,}") — still valid Markdown, fewer tokens; needed for the brief's own assertion — cost if wrong: none
- Task 5: Ruling: zero-chunk fallback emits headings as text chunks (with page/bbox) — layout model labels short OCR text as headings; otherwise a doc indexes to nothing — cost if wrong: heading-only docs index headings (desired)
- Task 5: Ruling: Important #1 (parse wraps converter construction + any Exception into permanent ParseError → infra failures never retried) — plan-mandated; fix: build converter outside the try; let MemoryError/OSError propagate (transient); wrap only conversion errors — cost if wrong: small
- Task 5: Ruling: Important #2 (ruled deviations untested) — fix: headings-only doc test + padded-table no-double-space test
- Task 5: Ruling: Important #3 (tiktoken vocab download) — covered by Task 7: Dockerfile sets TIKTOKEN_CACHE_DIR and warmup imports chunking at build — carry into Task 7 dispatch to verify offline
- Task 6: Ruling: Important #1 (stale document snapshot: overlapping ingestions let an older version become current; access/deleted payload from stale snapshot) — plan-mandated; fix: lock + re-read the document row (FOR UPDATE / populate_existing) before computing previous/superseded and before building the payload — cost if wrong: small
- Task 6: Ruling: Important #2 (post-commit old-point cleanup failure flips a READY version to queued/failed and leaks old points) — fix: post-commit cleanup errors are logged, never change status; Plan 3 retrieval must also accept only chunks whose version_id == document.current_version_id (covers leftovers) — carry into Plan 3 — cost if wrong: duplicate hits until Plan 3
- Task 6: Ruling: Important #3 (reject_on_worker_lost → poison file redelivered forever) — fix: drop task_reject_on_worker_lost — cost if wrong: a worker crash ends that attempt; version left in a processing stage (see #4)
- Task 6: Ruling: Important #4 (version stuck in a processing stage if worker dies / _finish fails) — fix: retry_version also accepts versions stuck in scanning..indexing whose updated_at is older than 30 minutes (STUCK_AFTER) — cost if wrong: admin can't recover stuck versions
- Task 6: Ruling: Important #5 (tests) — add deterministic overlap test (v2 completes inside v1's embed step), post-commit cleanup failure test, chunk-inspector version_id/foreign-version tests; Celery task test deferred
- Task 7: Ruling: Dockerfile also creates /app/.cache and chowns /app to appuser — warmup (as appuser) needs writable cache dirs; build failed otherwise — cost if wrong: none
- Task 7: Ruling: Important #1 (warmup layer after COPY app → every code change re-downloads models on rebuild) — plan-mandated; parked to Plan 8: split a model-prefetch layer that doesn't depend on app code — cost if wrong: slow rebuilds (minutes) until then
- Final: Ruling: Important #1 (collection-groups narrowed during worker indexing leaves old access_groups on new chunks; proven by probe) — fix: after the worker's READY commit, re-read effective access (and deleted/sensitive) in a fresh transaction and push it to the version's points; regression test — cost if wrong: small
- Final: Ruling: Important #2 (versions stuck in queued are unrecoverable and block re-upload as duplicates) — fix: retry_version treats queued older than STUCK_AFTER as stuck; upload catches enqueue failure → version failed (failed_stage "queued") and continues the batch — cost if wrong: small
- Final: Ruling: Important #3 (spec §3.3 payload lists `sensitive`; plan omitted it) — fix: add sensitive to chunk payload; collection sensitive toggle syncs payload — spec is binding — cost if wrong: small
- Final: Ruling: residual race in Finding 1 resync (admin change landing between resync read and write can be overwritten) — accepted: window is milliseconds and Plan 3's mandatory Postgres re-check of access/deleted per result makes it non-exploitable — cost if wrong: stale payload until next access change

## Deferred minor findings

- Task 1: minor (deferred): no tests for read of missing key / delete_prefix on missing or single file
- Task 1: minor (deferred): settings fixture now always starts Qdrant container (plan-mandated; slower tests)
- Task 1: minor (deferred): no positive-value validation on max_upload_mb / embedding_dimensions / chunk_* settings
- Task 2: minor (deferred): point_id test is tautological (should assert distinct IDs for different position/version)
- Task 2: minor (deferred): list_chunks truncates >1000 chunks without scroll pagination
- Task 2: minor (deferred): magic batch size 128 in upsert
- Task 2: minor (deferred): describe_image hardcodes image/png; non-text blocks dropped
- Task 2: minor (deferred): scan_bytes waits for clamd socket close before parsing (fine for INSTREAM); cancelled collector task not awaited
- Task 3: minor (deferred): collection name check-then-insert race → 500 instead of 409
- Task 3: minor (deferred): confirm_password has no failed-attempt limit/audit (brute force with stolen admin token)
- Task 3: minor (deferred): sync_collection_access includes soft-deleted docs (intended, undocumented/untested)
- Task 3: minor (deferred): lifespan: Qdrant client not closed if engine.dispose() raises
- Task 3: minor (deferred): documents.current_version_id has no FK (plan-mandated, avoids cycle)
- Task 4: minor (deferred): UploadResult.filename echoes raw client name, not sanitized
- Task 4: minor (deferred): duplicate check / version_no not concurrency-safe (race → dup or 500)
- Task 4: minor (deferred): list_documents returns [] for unknown collection instead of 404
- Task 4: minor (deferred): retry_version doesn't check deleted parent / latest version
- Task 4: minor (deferred): failed version of identical content blocks re-upload as duplicate (admin must retry)
- Task 4: minor (deferred): Office validation doesn't require [Content_Types].xml
- Task 4: minor (deferred): orphan original file if commit fails after store save
- Task 4: minor (deferred): test helper typing/inline import nits
- Task 4: minor (deferred): enqueue-on-failure test asserts count, not the specific version id
- Task 5: minor (deferred): chunk page/bbox from first buffered item only (page breaks); split parts share location
- Task 5: minor (deferred): no overlap carry-over across size-triggered buffer flushes
- Task 5: minor (deferred): token-slice decode can split multibyte chars; overlap>=max_tokens degenerates
- Task 5: minor (deferred): PARTIAL_SUCCESS accepted silently (dropped pages unsignalled)
- Task 5: minor (deferred): lru_cache converter construction not locked (double model load on concurrent first call)
- Task 5: minor (deferred): duplicated _png helper (parse.py/chunking.py)
- Task 5: minor (deferred): enrich uses assert; gather doesn't cancel siblings on failure
- Task 5: minor (deferred): heading equal to doc title dropped from header; weak .txt test assertion
- Task 5: minor (deferred): OSError retry also covers rare corrupt-file OSErrors from backends (retried up to 3x, then failed)
- Task 6: minor (deferred): superseded versions fully embedded (cost) and report chunk_count though points deleted
- Task 6: minor (deferred): _DONE excludes FAILED (redelivered failed message reruns)
- Task 6: minor (deferred): invalid version id retried 3x; backoff has no jitter
- Task 6: minor (deferred): tasks.py reads settings at import (broker_url)
- Task 6: minor (deferred): chunk inspector returns 200 [] for unknown/foreign version instead of 404
- Task 6: minor (deferred): page/figure PNGs of replaced/superseded versions never cleaned up
- Task 6: minor (deferred): embedder vector-count mismatch treated as transient
- Task 6: minor (deferred): row lock held during Qdrant I/O (serializes same-doc ingestions)
- Task 6: minor (deferred): a genuinely slow stage >30 min counts as stuck; admin retry could run two workers on one version (lock keeps swap correct)
- Task 6: minor (deferred): retry_version(now=naive datetime) would TypeError (no caller does)
- Task 7: minor (deferred): worker has no healthcheck (celery inspect ping)
- Task 7: minor (deferred): qdrant has no healthcheck (service_started)
- Task 7: minor (deferred): no mem_limit for worker (Docling CPU, concurrency 2)
- Task 7: minor (deferred): api healthcheck start_period 20s is thin on cold hosts
- Task 7: minor (deferred): redis without auth (internal only)
- Final: minor (deferred): _finish can downgrade a ready version to failed when overlapping runs fail (add status != ready guard)
- Final: minor (deferred): rejected (infected) originals never deleted/quarantined
- Final: minor (deferred): future group-delete path would silently widen restricted docs via CASCADE emptying restricted_groups
- Final: minor (deferred): restoring a soft-deleted doc whose content was re-uploaded creates two live docs with same content
- Final: minor (deferred): detect_kind accepts any image magic for any image ext; %PDF- required at offset 0
- Final: minor (deferred): mark_queue_failed DB fault → 500 loses earlier files' results in response
- Final: minor (deferred): retry endpoint enqueue failure → 500 (version recoverable after 30 min)
