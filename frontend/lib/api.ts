import type {
  Collection,
  Conversation,
  ConversationDetail,
  Message,
  SessionInfo,
  User,
} from "@/lib/types"

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string
  ) {
    super(message)
    this.name = "ApiError"
  }
}

const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"])
export const CSRF_HEADER = "X-CSRF-Protection"

async function toApiError(response: Response): Promise<ApiError> {
  let code = "http_error"
  let message = `Request failed (${response.status})`
  try {
    const body = await response.json()
    const detail = body?.detail
    if (Array.isArray(detail)) {
      code = "validation_error"
      message = detail[0]?.msg ?? message
    } else if (detail && typeof detail === "object") {
      code = detail.code ?? code
      message = detail.message ?? message
    }
  } catch {
    // non-JSON error body: keep the generic message
  }
  return new ApiError(response.status, code, message)
}

/** Same-origin fetch that adds the CSRF header to writes and throws ApiError on failure. */
export async function apiFetch(
  path: string,
  init: RequestInit = {}
): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase()
  const headers = new Headers(init.headers)
  if (UNSAFE.has(method)) headers.set(CSRF_HEADER, "1")
  if (
    init.body &&
    !(init.body instanceof FormData) &&
    !headers.has("Content-Type")
  ) {
    headers.set("Content-Type", "application/json")
  }
  const response = await fetch(path, {
    ...init,
    method,
    headers,
    credentials: "same-origin",
  })
  if (!response.ok) throw await toApiError(response)
  return response
}

export async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(path, init)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

/** Clear a stale cookie (so /login can't bounce back) and go to the sign-in page. */
export async function handleUnauthorized(
  navigate: (url: string) => void = (url) => window.location.assign(url),
  currentPath: () => string = () => window.location.pathname
): Promise<void> {
  try {
    await fetch("/api/auth/session", {
      method: "DELETE",
      headers: { [CSRF_HEADER]: "1" },
      credentials: "same-origin",
    })
  } catch {
    // offline: still go to the sign-in page
  } finally {
    // Already on the sign-in page: reloading it would loop on a persistent 401.
    if (currentPath() !== "/login") navigate("/login")
  }
}

export const pageImageUrl = (docId: string, page: number) =>
  `/api/documents/${docId}/pages/${page}`

const post = (body: unknown): RequestInit => ({
  method: "POST",
  body: JSON.stringify(body),
})

export const api = {
  me: () => apiJson<User>("/api/auth/me"),
  login: (username: string, password: string) =>
    apiJson<SessionInfo>("/api/auth/session", post({ username, password })),
  logout: () => apiJson<void>("/api/auth/session", { method: "DELETE" }),
  changePassword: (current_password: string, new_password: string) =>
    apiJson<SessionInfo>(
      "/api/auth/session/password",
      post({ current_password, new_password })
    ),
  collections: () => apiJson<Collection[]>("/api/collections"),
  conversations: (q?: string) =>
    apiJson<Conversation[]>(
      `/api/conversations${q ? `?q=${encodeURIComponent(q)}` : ""}`
    ),
  conversation: (id: string) =>
    apiJson<ConversationDetail>(`/api/conversations/${id}`),
  renameConversation: (id: string, title: string) =>
    apiJson<Conversation>(`/api/conversations/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),
  deleteConversation: (id: string) =>
    apiJson<void>(`/api/conversations/${id}`, { method: "DELETE" }),
  feedback: (messageId: string, rating: 1 | -1, comment?: string) =>
    apiJson<Message>(
      `/api/messages/${messageId}/feedback`,
      post({ rating, comment })
    ),
}
