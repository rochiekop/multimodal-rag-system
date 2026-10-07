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
