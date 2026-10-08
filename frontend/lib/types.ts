// Mirrors the backend response schemas (app/*/schemas.py).
export type Role = "user" | "admin" | "super_admin"

export interface Group {
  id: string
  name: string
  description: string
}

export interface User {
  id: string
  username: string
  full_name: string
  role: Role
  is_active: boolean
  must_change_password: boolean
  groups: Group[]
}

export interface SessionInfo {
  must_change_password: boolean
  user: User
}

export interface Collection {
  id: string
  name: string
  description: string
}

export interface Conversation {
  id: string
  title: string
  created_at: string
  updated_at: string
}

export interface Bbox {
  l: number
  t: number
  r: number
  b: number
}

export interface SourceCard {
  n: number
  doc_id: string
  version_id: string
  filename: string
  page: number | null
  bbox: Bbox | null
  page_image_scale: number | null
  heading_path: string[]
  modality: string
  score: number
  snippet: string
}

export type Outcome =
  | "answered"
  | "not_found"
  | "small_talk"
  | "blocked"
  | "support"
  | "off_topic"
  | "error"
  | "cancelled"

export interface Message {
  id: string
  role: "user" | "assistant"
  content: string
  outcome: Outcome | null
  sources: SourceCard[]
  citations: SourceCard[]
  low_confidence: boolean
  feedback_rating: 1 | -1 | null
  feedback_comment: string | null
  created_at: string
}

export interface ConversationDetail extends Conversation {
  messages: Message[]
}

export interface DoneData {
  message_id: string
  content: string
  outcome: Outcome
  citations: SourceCard[]
  low_confidence: boolean
  trace_id: string | null
  strikes?: number
  strike_limit?: number
  locked_until?: string | null
}

export type ChatEvent =
  | {
      event: "meta"
      data: { conversation_id: string; user_message_id: string }
    }
  | { event: "sources"; data: { sources: SourceCard[] } }
  | { event: "token"; data: { text: string } }
  | { event: "done"; data: DoneData }
  | {
      event: "error"
      data: { code: string; message: string; message_id?: string }
    }

// ---- Admin console (mirrors backend admin schemas) ----

export interface AdminUser extends User {
  locked_until: string | null
  chat_locked_until: string | null
  created_at: string
}

export interface UserCreate {
  username: string
  full_name: string
  password: string
  role: Role
  group_ids: string[]
}

export interface UserUpdate {
  full_name?: string
  role?: Role
  group_ids?: string[]
  is_active?: boolean
  unlock?: boolean
}

export interface AdminCollection extends Collection {
  sensitive: boolean
  groups: Group[]
  created_at: string
}

export interface CollectionInput {
  name: string
  description: string
  sensitive: boolean
  group_ids: string[]
}

export interface CollectionUpdate {
  name?: string
  description?: string
  sensitive?: boolean
  group_ids?: string[]
  password?: string
}

export type VersionStatus =
  | "queued"
  | "scanning"
  | "parsing"
  | "enriching"
  | "chunking"
  | "embedding"
  | "indexing"
  | "ready"
  | "failed"
  | "rejected"

export interface DocumentVersion {
  id: string
  version_no: number
  status: VersionStatus
  failed_stage: string | null
  error: string | null
  chunk_count: number
  page_count: number | null
  content_type: string
  size_bytes: number
  created_at: string
  updated_at: string
}

export interface AdminDocument {
  id: string
  collection_id: string
  filename: string
  current_version_id: string | null
  deleted_at: string | null
  restricted_groups: Group[]
  versions: DocumentVersion[]
  created_at: string
}

export interface UploadResult {
  filename: string
  outcome: "queued" | "duplicate" | "invalid"
  message: string
  document_id: string | null
  version_id: string | null
}

export interface Chunk {
  position: number
  text: string
  modality: string
  page: number | null
  heading_path: string[]
  extra: Record<string, unknown>
}

export interface AdminNotification {
  id: string
  kind: string
  title: string
  body: string
  target_type: string | null
  target_id: string | null
  created_at: string
  read_at: string | null
}

export interface DailyPoint {
  date: string
  questions: number
  cost_usd: number
  not_found: number
  low_confidence: number
  blocked: number
}

export interface Dashboard {
  days: number
  totals: {
    questions: number
    active_users: number
    input_tokens: number
    output_tokens: number
    cost_usd: number
    thumbs_up_rate: number | null
    not_found_rate: number | null
    low_confidence_rate: number | null
    guardrail_blocks: number
  }
  daily: DailyPoint[]
  ingestion: Record<string, number>
  health: Record<string, string>
}

export interface AuditEntry {
  id: number
  created_at: string
  actor_id: string | null
  actor_username: string | null
  action: string
  target_type: string | null
  target_id: string | null
  detail: Record<string, unknown>
  request_id: string | null
}

export interface AuditFilters {
  actor?: string
  action?: string
  target_type?: string
  target_id?: string
  since?: string
  until?: string
}

export type ReviewKind = "feedback" | "low_confidence" | "guardrail"

export interface ReviewItem {
  kind: ReviewKind
  id: string
  created_at: string
  user_id: string
  username: string
  message_id: string | null
  question: string | null
  answer: string | null
  detail: Record<string, unknown>
  reviewed_at: string | null
}

export interface MessageReview {
  conversation_id: string
  user: { id: string; username: string }
  question: string | null
  answer: {
    id: string
    content: string
    outcome: Outcome | null
    sources: SourceCard[]
    citations: SourceCard[]
    low_confidence: boolean
    guardrail: Record<string, unknown> | null
    feedback_rating: 1 | -1 | null
    feedback_comment: string | null
    trace_id: string | null
    created_at: string
  }
}

export interface EvalSet {
  id: string
  name: string
  description: string
  case_count: number
  created_at: string
}

export interface ExpectedSource {
  doc_id: string
  page: number | null
}

export interface EvalCase {
  id: string
  eval_set_id: string
  question: string
  expected_answer: string | null
  expected_sources: ExpectedSource[]
  collection_ids: string[]
  run_as_group_ids: string[]
  unanswerable: boolean
  origin: string
  source_message_id: string | null
  created_at: string
}

export interface CaseInput {
  question: string
  expected_answer: string | null
  expected_sources: ExpectedSource[]
  collection_ids: string[]
  run_as_group_ids: string[]
  unanswerable: boolean
}

export interface ImportResult {
  created: number
  errors: { row: number; message: string }[]
}

export type RunStatus = "queued" | "running" | "completed" | "failed"

export interface RunSummary {
  metrics?: Record<string, number | null>
  idk_accuracy?: number | null
  answered_rate?: number | null
  latency_p50_ms?: number | null
  latency_p95_ms?: number | null
  cost_per_question_usd?: number | null
  errors?: number
  score?: number | null
}

export interface EvalRun {
  id: string
  eval_set_id: string
  rag_config_id: string | null
  rag_config_version: number | null
  status: RunStatus
  error: string | null
  case_count: number
  summary: RunSummary
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface EvalResult {
  id: string
  case_id: string | null
  question: string
  unanswerable: boolean
  outcome: string
  answer: string
  sources: SourceCard[]
  metrics: Record<string, number | null>
  latency_ms: number
  cost_usd: number
  trace_id: string | null
  error: string | null
}

export interface EvalRunDetail extends EvalRun {
  results: EvalResult[]
}

export interface ComparedSide {
  outcome: string
  metrics: Record<string, number | null>
  answer: string
}

export interface Comparison {
  a: { id: string; summary: RunSummary }
  b: { id: string; summary: RunSummary }
  deltas: Record<string, number>
  questions: {
    case_id: string
    question: string
    a: ComparedSide
    b: ComparedSide
    regressed: boolean
    reasons: string[]
  }[]
}

export type CategoryAction = "block" | "flag" | "off"
export const MODERATION_CATEGORIES = [
  "violence",
  "hate",
  "harassment",
  "sexual",
  "illegal",
  "weapons",
  "self_harm",
] as const
export type ModerationCategory = (typeof MODERATION_CATEGORIES)[number]

export interface GuardrailSettings {
  rate_limit_per_minute: number
  max_question_chars: number
  moderation: Record<ModerationCategory, CategoryAction>
  self_harm_support: boolean
  injection_check: boolean
  exfiltration_check: boolean
  scope_check: boolean
  scope_description: string
  classifier_model: string
  blocked_message: string
  off_topic_message: string
  support_message: string
  pii_redaction: boolean
  pii_patterns: { name: string; regex: string }[]
  system_prompt_leak_check: boolean
  groundedness_check: boolean
  judge_model: string
  strike_limit: number
  strike_window_hours: number
  strike_lock_hours: number
  user_daily_cost_usd: number
  installation_daily_cost_usd: number
  cost_alert_ratio: number
}

export const RERANKER_MODELS = [
  "Xenova/ms-marco-MiniLM-L-12-v2",
  "Xenova/ms-marco-MiniLM-L-6-v2",
  "BAAI/bge-reranker-base",
  "jinaai/jina-reranker-v2-base-multilingual",
] as const

export interface RagConfig {
  chat_model: string
  rewrite_model: string
  fallback_model: string | null
  eval_judge_model: string
  reranker_model: (typeof RERANKER_MODELS)[number]
  search_top_k: number
  rerank_top_n: number
  rerank_threshold: number
  history_turns: number
  system_prompt: string
  rewrite_prompt: string
  not_found_message: string
  greeting_message: string
  prices: Record<string, { input_per_mtok: number; output_per_mtok: number }>
  guardrails: GuardrailSettings
}

export interface LatestEval {
  run_id: string
  eval_set_id: string
  score: number | null
  finished_at: string | null
}

export interface RagConfigVersion {
  id: string
  version: number
  note: string
  is_active: boolean
  created_at: string
  activated_at: string | null
  latest_eval: LatestEval | null
  config: RagConfig
}

export interface ActiveConfig {
  version: number | null
  config: RagConfig
  latest_eval: LatestEval | null
}

export interface Branding {
  app_name: string
  primary_color: string | null
  logo_url: string | null
}

export interface KeyStatus {
  source: "database" | "environment" | "none" | "unreadable"
  last4: string | null
  updated_at: string | null
  secrets_key_configured: boolean
}
