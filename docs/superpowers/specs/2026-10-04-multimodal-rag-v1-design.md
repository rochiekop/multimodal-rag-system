# Multimodal RAG System — v1 Design Spec

- **Date:** 2026-10-04
- **Status:** Draft, awaiting review
- **Scope:** Sub-project 1 (core platform + document RAG) and the essentials of sub-project 4 (admin, evaluation, monitoring, production hardening)

---

## 1. Product summary

An enterprise knowledge assistant that a company installs on its own infrastructure. Admins load the company's documents, including PDFs with tables and charts, office files, slides, scans and images. Employees ask questions in natural language and get accurate answers with citations, limited to the documents they are permitted to see.

The product has two sides:

- **User app (`/app`):** ask questions, read cited answers, view sources, give feedback.
- **Admin console (`/admin`):** manage documents, collections, users and permissions; evaluate answer quality; configure models, prompts and guardrails; review flagged answers; read audit logs.

### 1.1 Decisions made

| Topic | Decision |
|---|---|
| Deployment model | **Single-tenant**: one installation per company |
| Installation | **Docker Compose**, one `docker compose up -d` |
| Scale target | **Medium–large**: 10k–100k documents, up to ~10M chunks per installation |
| Models | **Cloud APIs by default** (Claude / OpenAI / Gemini); **self-hosted models optional** (vLLM / Ollama / TEI) |
| Backend | Python, **FastAPI**, **LangChain** |
| Frontend | **Next.js** (App Router), Tailwind v4, [shadcn/ui](https://ui.shadcn.com/); one app with `/app` and `/admin` areas; built from **official shadcn/ui components and blocks** ([shadcn-ui/ui](https://github.com/shadcn-ui/ui)), see 6.8 |
| Search store | **Qdrant** (dense + sparse hybrid) |
| App data | **PostgreSQL** |
| File store | **MinIO** |
| Job queue | **Celery + Redis** |
| Observability | **Arize Phoenix** (LLM tracing) + admin dashboard from Postgres |
| Evaluation | **Ragas** metrics, run in our worker |
| User onboarding | **Admins create users directly**; no email invites, no SMTP dependency |

### 1.2 Success criteria

1. A user only ever receives answers and sources drawn from documents they are permitted to see. This is verified by an automated security test suite.
2. Answers cite the source document, page and region, and the UI shows a page preview with the cited region highlighted.
3. When the documents do not contain the answer, the system says so instead of inventing one.
4. Admins can measure answer quality with test sets and compare configurations before activating a change.
5. The system ingests mixed-format documents reliably in the background (retries, visible status, no duplicates) and stays responsive at ~10M chunks.
6. A fresh install works from `.env` + `docker compose up -d` + `make create-superadmin`.

### 1.3 Out of scope for v1 (designed to be added later)

- Audio and video ingestion (sub-project 2): added as new ingestion parsers
- Domain-specific modes (sub-project 3): added as parsers, prompts and RagConfig presets
- SSO / OIDC / SAML (auth module keeps a hook for it)
- Email invites and password reset by email
- Connectors (SharePoint, Google Drive, Confluence)
- Multi-tenant SaaS mode
- Agentic tools and LangGraph; the assistant stays **read-only**
- Synthetic test generation, adversarial eval set, nightly scheduled evals, blocking activation gate
- Prometheus/Grafana, webhook alerts, anomaly-detection alerts
- Billing

---

## 2. Architecture

### 2.1 Services (`deploy/docker-compose.yml`)

| Service | Role |
|---|---|
| `caddy` | Reverse proxy, automatic HTTPS; `/` → frontend, `/api` → api |
| `frontend` | Next.js app (user app + admin console) |
| `api` | FastAPI; the only backend the frontend talks to; enforces auth and permissions |
| `worker` | Celery workers (same Python codebase): ingestion and evaluation jobs; horizontally scalable |
| `postgres` | App data: users, groups, documents, collections, conversations, configs, evals, audit log, Phoenix storage |
| `qdrant` | Chunk index: dense + sparse vectors with payload metadata |
| `minio` | Original files, converted PDFs, rendered page images, extracted figures |
| `redis` | Celery broker, rate-limit counters, caches |
| `gotenberg` | Converts office formats to PDF (LibreOffice) |
| `clamav` | Virus scan of uploads |
| `phoenix` | LLM tracing and experiment UI |

Optional Compose profile **`local-models`** adds self-hosted model servers (vLLM or Ollama for the LLM, Hugging Face Text Embeddings Inference for embeddings and the reranker).

### 2.2 Backend modules

Each module has one purpose and exposes a small Python interface. API routers stay thin and call these interfaces. **LangChain is used only inside `llm`, `ingestion`, `retrieval`, `chat` and `guardrails`**, so LangChain API changes stay contained.

| Module | Responsibility | Key interface (illustrative) |
|---|---|---|
| `core` | Settings, DB session, logging, request IDs, encryption of secrets | — |
| `auth` | Login, JWT, password hashing, role checks, lockout | `current_user()`, `require_role(role)` |
| `users` | Users, groups, strikes, suspension | `create_user`, `assign_groups` |
| `documents` | Documents, versions, collections, access groups, soft delete | `register_upload`, `effective_access(doc)` |
| `ingestion` | Pipeline stages and Celery tasks | `ingest(document_version_id)` |
| `retrieval` | Permission filter, hybrid search, rerank | `retrieve(query, user, collections, config) -> list[Chunk]` |
| `chat` | Conversations, answer chain, citations, feedback | `answer(question, user, conversation, config) -> stream` |
| `guardrails` | Input, output and operational checks | `check_input(...)`, `check_output(...)` |
| `evaluation` | Test sets, runs, scoring, comparison | `run_eval(test_set, config_version)` |
| `llm` | Model gateway, `RagConfig` versions | `get_chat_model(role, config)`, `get_embeddings(config)` |
| `audit` | Append-only audit log | `audit.record(actor, action, target, detail)` |

---

## 3. Ingestion pipeline

### 3.1 Supported inputs
pdf, doc/docx, ppt/pptx, xls/xlsx/csv, md, txt, html, png/jpg/tiff (including scans). Admins can upload single files, multiple files or a zip.

### 3.2 Upload (synchronous, API)
1. Validate the **real file type from file content** (not the extension), enforce the size limit, and protect against zip bombs.
2. Compute a **SHA-256** hash of the content. Identical content already present → flagged as a duplicate and not re-ingested. Same filename in the same collection with different content → new **version** of that document.
3. Store the original in MinIO, create a `DocumentVersion` with status `queued`, enqueue an ingestion job, and return immediately.

### 3.3 Processing (worker)

`scan → convert → parse → enrich → chunk → embed → index → ready`

| Stage | Behavior |
|---|---|
| Scan | ClamAV. Infected → status `rejected`, stop. |
| Convert | Office formats → PDF via Gotenberg; macros are not executed or preserved. md/txt/html/images skip this stage. |
| Parse | Docling (via `langchain-docling`): layout, reading order, headings, tables as Markdown, figures, OCR for scanned pages. Render page images to MinIO. |
| Enrich | A vision LLM writes a searchable description of each figure, chart or image. Large tables get a short summary in addition to the table Markdown. |
| Chunk | Structure-aware chunks of ~500 tokens with overlap. Tables and figures are never split. Each chunk is prefixed with a context header: `Doc title › Section › Subsection`. |
| Embed | Dense embedding plus sparse BM25 vector per chunk, in batches. |
| Index | Upsert to Qdrant with payload: `doc_id, version_id, page, bbox, heading_path, collection_id, access_groups, modality (text/table/figure), sensitive`. |

### 3.4 Reliability rules
- **Idempotent stages:** chunk IDs are deterministic (derived from version ID + chunk position), so retries never duplicate.
- **Retries:** Celery retries with exponential backoff. After the final failure, status is `failed`, and the failing stage and error are visible in the admin console with a **Retry** action.
- **Version swap:** the new version is fully indexed before the old version's chunks are deleted, so there is no gap in answerability.
- **Permission or collection changes** update Qdrant payloads directly, without re-embedding.
- **Status tracking:** `queued → scanning → converting → parsing → enriching → chunking → embedding → indexing → ready | failed | rejected`, shown live in the admin console, along with queue depth.

---

## 4. Retrieval and answering

### 4.1 Flow
`question → input guardrails → permission filter → rewrite → hybrid search → rerank → confidence check → generate (stream) → output guardrails → cite → log`

1. **Input guardrails** (section 5).
2. **Permission filter:** a Qdrant filter built server-side from the user's access groups ∩ selected collections, excluding soft-deleted documents. Applied inside the search query. Never taken from the client.
3. **Rewrite:** follow-up questions are condensed into a standalone question using chat history and a small, fast model. Skipped on the first turn.
4. **Hybrid search:** dense + sparse in Qdrant, fused with RRF; top 50 candidates (configurable).
5. **Rerank:** cross-encoder reranker (Cohere Rerank by default; local bge-reranker in self-hosted mode); keep the top ~8 (configurable).
6. **Confidence check:** if the top rerank score is below the threshold, return "I couldn't find this in the available documents" with the closest matches, and do not call the LLM.
7. **Generate:** numbered sources in delimited blocks (tables as Markdown, figures as descriptions; page images included when the model supports vision and figure chunks rank highly). The system prompt requires answering only from the sources, citing `[n]`, stating when the sources are insufficient, and ignoring any instructions that appear inside the sources. Streamed to the client over SSE.
8. **Output guardrails** (section 5).
9. **Cite:** each `[n]` maps to `doc_id, page, bbox`. Citation numbers that don't match a source are removed. The UI renders source cards with a page preview and the highlighted region.
10. **Log:** store question, answer, sources, scores, latency, token counts, computed cost and Phoenix trace ID on the message.

### 4.2 RagConfig
A versioned configuration object stored in Postgres. It holds: chat model, rewrite model, vision model, judge model, fallback model, embedding model, reranker, top-k values, rerank threshold, chunk size/overlap, prompts, and guardrail settings. Every edit creates a new version, and exactly one version is **active**. Activation and rollback are `super_admin` actions and are audited. Changing the embedding model or chunk settings requires re-indexing, so the console warns about this and offers a re-index job.

---

## 5. Guardrails and abuse protection

All checks are small LangChain runnables in the `guardrails` module, configurable in the admin console. Every block or flag is written to the audit log and appears in the review queue.

### 5.1 Input
| Check | Behavior |
|---|---|
| Rate and size limits | Per-user questions/minute and max question length (Redis) |
| Jailbreak / prompt-injection detection | Fast classifier model → block with a polite message |
| Content moderation | Categories: violence, hate, harassment, sexual, illegal activity, weapons, self-harm. Block or flag per category (configurable). Provider moderation by default; Llama Guard in self-hosted mode. |
| Self-harm handling | Supportive message with admin-configurable help resources; flagged privately |
| Scope check (optional) | Off-topic requests are politely redirected |
| Exfiltration patterns | Requests to dump full documents verbatim or enumerate sensitive data are blocked for collections marked `sensitive` |

### 5.2 Output
| Check | Behavior |
|---|---|
| Citation validation | Remove citations that don't match a real source |
| PII leak check | Redact PII (national IDs, card numbers, etc.) that is **not** present in the user's permitted sources for this answer |
| Groundedness check | After streaming, a fast judge checks the answer's claims against the sources. Unsupported → "⚠ Low confidence — verify sources" badge + review queue. |
| System-prompt leak | Block answers reproducing the system prompt |

### 5.3 Operational and account protection
- **Strike system:** repeated violations → warning → temporary lock (default 3 strikes / 24h) → in-app notification to admins. Admins can unlock or suspend.
- **Cost caps:** daily token/spend limits per user and per installation, computed from stored token counts; in-app alert to admins as a cap approaches.
- **Timeouts and fallback:** one retry, then the configured fallback model; a clear error message if no model is reachable.
- **Read-only assistant:** the AI has no tools and cannot modify data or call external systems.
- **Role checks on every API route** (server-side).
- **Destructive admin actions** (delete documents/collections, activate RagConfig, bulk permission changes) require a confirmation dialog **and password re-entry**. Deletes are soft (restorable for 30 days). All are audited.
- **Web security:** sanitized Markdown rendering, CSRF protection, secure httpOnly cookies, strict CORS, Pydantic validation on all input, ORM-only SQL, login lockout after repeated failed attempts.

---

## 6. Users, permissions and apps

### 6.1 Permission model
`User → Groups → Collections → Documents`
- Collections grant access to groups.
- A document may be **restricted further** to a subset of its collection's groups, never widened.
- Each chunk stores the document's **effective access groups** for fast filtering.

### 6.2 Roles
| Role | Permissions |
|---|---|
| `user` | Ask questions, view permitted sources, give feedback, manage own conversations |
| `admin` | Documents, collections, users, groups, evaluation, review queue, audit log |
| `super_admin` | Admin rights + model/API keys, RagConfig activation, guardrail settings, managing admins |

### 6.3 Accounts
- **Admins create users directly** with an initial password. The user **must change it at first login**.
- Argon2 password hashing; a single signed JWT access token valid for **8 hours** (users log in again after it expires). Tokens are revoked immediately on suspension, role change, password change or admin password reset. A refresh-token flow may be added with the frontend (Plan 6) if needed.
- The first `super_admin` is created with `make create-superadmin`.

### 6.4 User app (`/app`)
- Chat with a collection picker, streaming answers, citation cards (page preview + highlight), 👍/👎 with an optional comment, low-confidence badge
- Conversation history: search, rename, delete
- Source viewer: opens a permitted document at the cited page
- Profile: password change

### 6.5 Admin console (`/admin`)
| Page | Purpose |
|---|---|
| Dashboard | Questions/day, active users, tokens/cost, 👍 rate, "I don't know" rate, low-confidence rate, guardrail blocks, ingestion queue, service health |
| Documents | Upload, live status, versions, retry, soft delete/restore, **chunk inspector** |
| Collections & access | Create collections, assign groups, mark `sensitive` |
| Users & groups | Create users, roles, groups, suspend/unlock, strikes |
| Evaluation | Test sets, runs, comparisons |
| Review queue | 👎 answers, low-confidence answers, guardrail flags; one-click "add to test set" |
| Models & RAG config | Edit, version, compare eval scores, activate, roll back |
| Guardrails | Toggles and thresholds per check and category |
| Audit log | Append-only, filterable, CSV export |
| Settings | Provider API keys (encrypted at rest), cost caps, fallback model, branding |
| Notifications | In-app alerts (ingestion failures, cost caps, eval drops, strike locks) |

### 6.6 Privacy
Admins see user conversations only through the review queue. Every admin view of a user's conversation is audited.

### 6.8 Frontend foundation
- **Base:** a fresh Next.js (App Router, TypeScript, Tailwind v4) app initialized with the **official shadcn/ui CLI** (`npx shadcn@latest init`), using components and blocks from the official registry ([ui.shadcn.com](https://ui.shadcn.com/), source [shadcn-ui/ui](https://github.com/shadcn-ui/ui), MIT). Components are copied into `frontend/components/ui` and owned by the project. Supporting libraries are the ones shadcn uses: Recharts (charts), TanStack Table (data tables), react-hook-form + zod (forms), lucide-react (icons), sonner (toasts), next-themes (light/dark).
- **Admin console (`/admin`):** built on the official **`dashboard-01`** block (sidebar, site header, section cards, interactive area chart, data table):
  - Dashboard page: section cards + charts
  - Documents, Users & groups, Audit log, Review queue, Evaluation runs: the block's data table pattern
  - Settings, Guardrails, Models & RAG config: forms built from shadcn `form`, `input`, `select`, `switch`, `tabs`
- **User app (`/app`):** shadcn `sidebar` (conversation history) + a chat view built from shadcn components (`scroll-area`, `textarea`, `card`, `avatar`, `hover-card`, `sheet` for the source viewer). There is no official chat block, so the chat UI is our own composition.
- **Auth pages:** sign-in from an official **login block** (e.g. `login-03`) plus a forced password-change page with the same layout. No sign-up or forgot-password pages, because v1 has no self-registration and no email.
- **Theming:** shadcn CSS variables with light/dark mode; branding (logo, primary color) is configurable in admin Settings.

### 6.9 Audit log
Append-only table. It records: logins and failures, user/group/role changes, uploads, deletes, restores, permission changes, RagConfig edits and activations, guardrail blocks and flags, strike locks, and admin views of conversations. Each entry has actor, action, target, details (JSON), timestamp and request ID.

---

## 7. Evaluation and monitoring (v1, kept simple)

### 7.1 Evaluation
- **Test sets:** cases with question, optional expected answer, optional expected sources (doc/page), collection scope and run-as access groups. Cases can be created manually, by CSV import, or from the review queue. Test sets should include **unanswerable** cases.
- **Runs:** test set + RagConfig version → Celery job runs the real pipeline (same permissions and guardrails) → scored with Ragas using the judge model:
  - Retrieval: hit rate@k (when expected sources are given), context precision, context recall
  - Answer: faithfulness, answer relevance, correctness vs expected answer (when given)
  - Behavior: "I don't know" accuracy on unanswerable cases
  - Operational: latency p50/p95, cost per question
- **Compare:** two runs side by side, per-question, with regressions highlighted.
- **Activation warning:** when activating a RagConfig, the console shows its latest eval score next to the active config's. This is a warning, not a block.
- Runs are also recorded as Phoenix experiments for deeper analysis.

### 7.2 Monitoring
- **Phoenix:** LangChain auto-instrumentation via OpenTelemetry; every question traced end to end; admin console links each message to its trace.
- **Dashboard:** computed from Postgres (section 6.5).
- **Alerts:** in-app notifications only.
- **Logs:** structured JSON with a request ID propagated frontend → api → worker → Phoenix.
- **Health:** `/health` endpoints and Docker health checks for every service.

---

## 8. Deployment

### 8.1 Repository layout
```
multimodal-rag-system/
├── backend/
│   ├── app/{core,auth,users,documents,ingestion,retrieval,chat,guardrails,evaluation,llm,audit,api}/
│   ├── app/worker.py
│   ├── migrations/          # Alembic
│   ├── tests/
│   └── pyproject.toml       # uv
├── frontend/                # Next.js App Router, Tailwind, shadcn/ui
├── deploy/
│   ├── docker-compose.yml
│   ├── Caddyfile
│   └── .env.example
├── scripts/                 # create-superadmin, backup, restore
├── docs/
└── Makefile
```

### 8.2 Install and upgrade
1. `cp deploy/.env.example deploy/.env` and set the domain, secrets and API keys.
2. `docker compose up -d`. Migrations run automatically on API start.
3. `make create-superadmin`.

To upgrade: pull new images and run `docker compose up -d`; migrations apply automatically.

### 8.3 Production details
- Multi-stage images, non-root users, pinned versions, named volumes, health checks with `depends_on: condition: service_healthy`.
- `make backup` / `make restore`: Postgres dump + Qdrant snapshot + MinIO mirror into one timestamped folder.
- Qdrant: **int8 scalar quantization** in RAM, original vectors on disk (~4× memory reduction).
- Sizing guidance: medium ≈ 4 vCPU / 16 GB RAM; large (~10M chunks) ≈ 8 vCPU / 32 GB RAM / 500 GB SSD.

---

## 9. Testing strategy

TDD throughout.

| Level | Coverage |
|---|---|
| Unit (pytest) | Every module in isolation; LangChain fake chat models and embeddings for deterministic, free tests |
| Integration (testcontainers) | Real Postgres, Qdrant, Redis, MinIO; end-to-end ingestion of fixture files (PDF with table, scanned image, pptx, docx, md) |
| Security suite | Users never retrieve chunks outside their access, including after permission changes and version swaps; an automatic test verifies **every API route** has auth and role checks; guardrail tests with harmful and injection prompts |
| Frontend E2E (Playwright) | Login → ask → citation shown; admin upload → status reaches `ready` |
| CI (GitHub Actions) | ruff, mypy, eslint, all tests, Docker image builds on every push |

---

## 10. Extension points for later sub-projects

- **Audio/video (sub-project 2):** new ingestion parsers producing chunks with `modality=audio|video` and timestamp metadata instead of page/bbox; citations render a player at the timestamp.
- **Domain modes (sub-project 3):** domain-specific parsers registered in `ingestion`, plus RagConfig presets (prompts, chunking, metadata fields) and domain test sets.
- **SSO:** an additional auth provider in `auth`, mapping identity-provider groups to app groups.
