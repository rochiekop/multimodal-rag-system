import { apiJson } from "@/lib/api"
import type {
  ActiveConfig,
  AdminCollection,
  AdminDocument,
  AdminNotification,
  AdminUser,
  AuditEntry,
  AuditFilters,
  Branding,
  CaseInput,
  Chunk,
  CollectionInput,
  CollectionUpdate,
  Comparison,
  Dashboard,
  DocumentVersion,
  EvalCase,
  EvalRun,
  EvalRunDetail,
  EvalSet,
  Group,
  ImportResult,
  KeyStatus,
  MessageReview,
  RagConfig,
  RagConfigVersion,
  ReviewItem,
  ReviewKind,
  UploadResult,
  UserCreate,
  UserUpdate,
} from "@/lib/types"

type Params = Record<string, string | number | boolean | null | undefined>

/** Query string from the defined, non-empty params ("" when there are none). */
export function qs(params: Params): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "")
      search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ""
}

const send = (method: string, body?: unknown): RequestInit => ({
  method,
  body: body === undefined ? undefined : JSON.stringify(body),
})

function upload<T>(path: string, files: File[], field: string): Promise<T> {
  const form = new FormData()
  for (const file of files) form.append(field, file)
  return apiJson<T>(path, { method: "POST", body: form })
}

const A = "/api/admin"

export const adminApi = {
  dashboard: (days: number) =>
    apiJson<Dashboard>(`${A}/dashboard?days=${days}`),
  notifications: (unread = false) =>
    apiJson<AdminNotification[]>(
      `${A}/notifications${qs({ unread: unread || undefined })}`
    ),
  markNotificationRead: (id: string) =>
    apiJson<AdminNotification>(`${A}/notifications/${id}/read`, send("POST")),

  users: () => apiJson<AdminUser[]>(`${A}/users`),
  createUser: (body: UserCreate) =>
    apiJson<AdminUser>(`${A}/users`, send("POST", body)),
  updateUser: (id: string, body: UserUpdate) =>
    apiJson<AdminUser>(`${A}/users/${id}`, send("PATCH", body)),
  resetPassword: (id: string, new_password: string) =>
    apiJson<AdminUser>(
      `${A}/users/${id}/reset-password`,
      send("POST", { new_password })
    ),
  groups: () => apiJson<Group[]>(`${A}/groups`),
  createGroup: (body: { name: string; description: string }) =>
    apiJson<Group>(`${A}/groups`, send("POST", body)),

  collections: () => apiJson<AdminCollection[]>(`${A}/collections`),
  createCollection: (body: CollectionInput) =>
    apiJson<AdminCollection>(`${A}/collections`, send("POST", body)),
  updateCollection: (id: string, body: CollectionUpdate) =>
    apiJson<AdminCollection>(`${A}/collections/${id}`, send("PATCH", body)),

  documents: (collectionId: string, includeDeleted: boolean) =>
    apiJson<AdminDocument[]>(
      `${A}/collections/${collectionId}/documents${qs({ include_deleted: includeDeleted || undefined })}`
    ),
  document: (id: string) => apiJson<AdminDocument>(`${A}/documents/${id}`),
  uploadDocuments: (collectionId: string, files: File[]) =>
    upload<UploadResult[]>(
      `${A}/collections/${collectionId}/documents`,
      files,
      "files"
    ),
  setDocumentGroups: (id: string, group_ids: string[]) =>
    apiJson<AdminDocument>(
      `${A}/documents/${id}/groups`,
      send("PUT", { group_ids })
    ),
  deleteDocument: (id: string, password: string) =>
    apiJson<AdminDocument>(
      `${A}/documents/${id}/delete`,
      send("POST", { password })
    ),
  restoreDocument: (id: string) =>
    apiJson<AdminDocument>(`${A}/documents/${id}/restore`, send("POST")),
  retryVersion: (versionId: string) =>
    apiJson<DocumentVersion>(`${A}/versions/${versionId}/retry`, send("POST")),
  chunks: (documentId: string, versionId?: string) =>
    apiJson<Chunk[]>(
      `${A}/documents/${documentId}/chunks${qs({ version_id: versionId })}`
    ),

  audit: (filters: AuditFilters, beforeId?: number, limit = 50) =>
    apiJson<AuditEntry[]>(
      `${A}/audit${qs({ ...filters, before_id: beforeId, limit })}`
    ),
  auditExportUrl: (filters: AuditFilters) =>
    `${A}/audit/export${qs({ ...filters })}`,

  reviewQueue: (
    kind: ReviewKind | undefined,
    includeReviewed: boolean,
    offset = 0
  ) =>
    apiJson<ReviewItem[]>(
      `${A}/review-queue${qs({ kind, include_reviewed: includeReviewed || undefined, limit: 50, offset })}`
    ),
  reviewMessage: (messageId: string) =>
    apiJson<MessageReview>(`${A}/review-queue/messages/${messageId}`),
  markReviewed: (kind: ReviewKind, itemId: string) =>
    apiJson<void>(`${A}/review-queue/${kind}/${itemId}/reviewed`, send("POST")),
  addToEvalSet: (
    messageId: string,
    body: {
      eval_set_id: string
      expected_answer: string | null
      unanswerable: boolean
    }
  ) =>
    apiJson<EvalCase>(
      `${A}/review-queue/messages/${messageId}/add-to-eval-set`,
      send("POST", body)
    ),

  evalSets: () => apiJson<EvalSet[]>(`${A}/eval-sets`),
  evalSet: (id: string) => apiJson<EvalSet>(`${A}/eval-sets/${id}`),
  createEvalSet: (body: { name: string; description: string }) =>
    apiJson<EvalSet>(`${A}/eval-sets`, send("POST", body)),
  deleteEvalSet: (id: string) =>
    apiJson<void>(`${A}/eval-sets/${id}`, send("DELETE")),
  evalCases: (setId: string) =>
    apiJson<EvalCase[]>(`${A}/eval-sets/${setId}/cases`),
  createCase: (setId: string, body: CaseInput) =>
    apiJson<EvalCase>(`${A}/eval-sets/${setId}/cases`, send("POST", body)),
  deleteCase: (caseId: string) =>
    apiJson<void>(`${A}/eval-cases/${caseId}`, send("DELETE")),
  importCases: (setId: string, file: File) =>
    upload<ImportResult>(`${A}/eval-sets/${setId}/import`, [file], "file"),
  evalRuns: (setId?: string) =>
    apiJson<EvalRun[]>(`${A}/eval-runs${qs({ eval_set_id: setId })}`),
  evalRun: (id: string) => apiJson<EvalRunDetail>(`${A}/eval-runs/${id}`),
  startRun: (body: { eval_set_id: string; rag_config_id: string | null }) =>
    apiJson<EvalRun>(`${A}/eval-runs`, send("POST", body)),
  compareRuns: (a: string, b: string) =>
    apiJson<Comparison>(`${A}/eval-runs/compare${qs({ a, b })}`),

  ragConfigs: () => apiJson<RagConfigVersion[]>(`${A}/rag-configs`),
  activeConfig: () => apiJson<ActiveConfig>(`${A}/rag-configs/active`),
  createConfig: (config: RagConfig, note: string) =>
    apiJson<RagConfigVersion>(
      `${A}/rag-configs`,
      send("POST", { config, note })
    ),
  activateConfig: (id: string, password: string) =>
    apiJson<RagConfigVersion>(
      `${A}/rag-configs/${id}/activate`,
      send("POST", { password })
    ),

  updateBranding: (body: { app_name: string; primary_color: string | null }) =>
    apiJson<Branding>(`${A}/settings/branding`, send("PUT", body)),
  uploadLogo: (file: File) =>
    upload<Branding>(`${A}/settings/branding/logo`, [file], "file"),
  removeLogo: () =>
    apiJson<Branding>(`${A}/settings/branding/logo`, send("DELETE")),
  openaiKey: () => apiJson<KeyStatus>(`${A}/settings/openai-key`),
  setOpenaiKey: (api_key: string, password: string) =>
    apiJson<KeyStatus>(
      `${A}/settings/openai-key`,
      send("PUT", { api_key, password })
    ),
  clearOpenaiKey: (password: string) =>
    apiJson<KeyStatus>(
      `${A}/settings/openai-key/clear`,
      send("POST", { password })
    ),
}
