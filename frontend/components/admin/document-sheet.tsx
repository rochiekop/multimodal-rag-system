"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { toast } from "sonner"

import { GroupChecklist } from "@/components/admin/group-checklist"
import { PasswordDialog } from "@/components/admin/password-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Separator } from "@/components/ui/separator"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { adminApi } from "@/lib/admin-api"
import { ApiError } from "@/lib/api"
import { formatBytes, formatDateTime } from "@/lib/format"
import type { AdminCollection, AdminDocument, VersionStatus } from "@/lib/types"

const DONE: VersionStatus[] = ["ready", "failed", "rejected"]
export const isProcessing = (status: VersionStatus) => !DONE.includes(status)

/** The newest version: what the admin is waiting on (it may not be current yet). */
export const latestVersion = (doc: AdminDocument) =>
  [...doc.versions].sort((a, b) => b.version_no - a.version_no)[0]

export function StatusBadge({ status }: { status: VersionStatus }) {
  if (status === "ready") return <Badge variant="secondary">Ready</Badge>
  if (status === "failed" || status === "rejected")
    return (
      <Badge variant="destructive">
        {status === "failed" ? "Failed" : "Rejected"}
      </Badge>
    )
  return (
    <Badge variant="outline">
      {status[0].toUpperCase() + status.slice(1)}…
    </Badge>
  )
}

const errorText = (error: unknown) =>
  error instanceof ApiError ? error.message : "Something went wrong. Try again."

/** Keyed by the saved restriction, so its local selection re-initialises from props. */
function AccessSection({
  documentId,
  collection,
  initial,
  onSaved,
}: {
  documentId: string
  collection: AdminCollection | undefined
  initial: string[]
  onSaved: () => void
}) {
  const [access, setAccess] = useState<string[]>(initial)
  const saveAccess = useMutation({
    mutationFn: () => adminApi.setDocumentGroups(documentId, access),
    onSuccess: () => {
      toast.success("Access updated")
      onSaved()
    },
    onError: (e) => toast.error(errorText(e)),
  })
  return (
    <section className="grid gap-2">
      <h3 className="text-sm font-medium">Access</h3>
      <p className="text-sm text-muted-foreground">
        Leave all unchecked to give every group of the collection access, or
        pick a subset to restrict this document further.
      </p>
      <GroupChecklist
        groups={collection?.groups ?? []}
        value={access}
        onChange={setAccess}
        idPrefix="doc-group"
      />
      <div>
        <Button
          size="sm"
          variant="outline"
          disabled={saveAccess.isPending}
          onClick={() => saveAccess.mutate()}
        >
          Save access
        </Button>
      </div>
    </section>
  )
}

export function DocumentSheet({
  documentId,
  collection,
  onOpenChange,
}: {
  documentId: string | null
  collection: AdminCollection | undefined
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const [deleting, setDeleting] = useState(false)
  const [filter, setFilter] = useState("")

  const { data: doc } = useQuery({
    queryKey: ["admin", "document", documentId],
    queryFn: () => adminApi.document(documentId!),
    enabled: !!documentId,
    refetchInterval: (query) => {
      const latest = query.state.data && latestVersion(query.state.data)
      return latest && isProcessing(latest.status) ? 5000 : false
    },
  })
  const current = doc?.versions.find((v) => v.id === doc.current_version_id)
  const chunks = useQuery({
    queryKey: ["admin", "chunks", documentId, current?.id],
    queryFn: () => adminApi.chunks(documentId!, current!.id),
    enabled: !!documentId && current?.status === "ready",
  })

  const refresh = () => {
    void queryClient.invalidateQueries({
      queryKey: ["admin", "document", documentId],
    })
    void queryClient.invalidateQueries({ queryKey: ["admin", "documents"] })
  }
  const retry = useMutation({
    mutationFn: adminApi.retryVersion,
    onSuccess: () => {
      toast.success("Queued for processing again")
      refresh()
    },
    onError: (e) => toast.error(errorText(e)),
  })
  const restore = useMutation({
    mutationFn: () => adminApi.restoreDocument(documentId!),
    onSuccess: () => {
      toast.success("Document restored")
      refresh()
    },
    onError: (e) => toast.error(errorText(e)),
  })

  const needle = filter.trim().toLowerCase()
  const shownChunks = (chunks.data ?? []).filter(
    (c) => !needle || c.text.toLowerCase().includes(needle)
  )
  const restrictedIds = doc?.restricted_groups.map((g) => g.id) ?? []

  return (
    <Sheet open={!!documentId} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-2xl">
        <SheetHeader>
          <SheetTitle>{doc?.filename ?? "Document"}</SheetTitle>
          <SheetDescription>
            {doc?.deleted_at
              ? `Deleted ${formatDateTime(doc.deleted_at)}; restorable for 30 days.`
              : collection?.name}
          </SheetDescription>
        </SheetHeader>
        {doc && (
          <div className="grid gap-6 px-4 pb-6">
            <section className="grid gap-2">
              <h3 className="text-sm font-medium">Versions</h3>
              {[...doc.versions]
                .sort((a, b) => b.version_no - a.version_no)
                .map((v) => (
                  <div
                    key={v.id}
                    className="grid gap-1 rounded-md border p-3 text-sm"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">v{v.version_no}</span>
                      <StatusBadge status={v.status} />
                      {v.id === doc.current_version_id && (
                        <Badge variant="outline">Current</Badge>
                      )}
                      <span className="text-muted-foreground">
                        {v.chunk_count} chunks · {v.page_count ?? "—"} pages ·{" "}
                        {formatBytes(v.size_bytes)} ·{" "}
                        {formatDateTime(v.created_at)}
                      </span>
                      {v.status === "failed" && (
                        <Button
                          size="sm"
                          variant="outline"
                          className="ml-auto"
                          disabled={retry.isPending}
                          onClick={() => retry.mutate(v.id)}
                        >
                          Retry
                        </Button>
                      )}
                    </div>
                    {v.error && (
                      <p className="text-destructive">
                        {v.failed_stage ? `${v.failed_stage}: ` : ""}
                        {v.error}
                      </p>
                    )}
                  </div>
                ))}
            </section>
            <Separator />
            <AccessSection
              key={`${doc.id}:${restrictedIds.join(",")}`}
              documentId={doc.id}
              collection={collection}
              initial={restrictedIds}
              onSaved={refresh}
            />
            <Separator />
            <section className="grid gap-2">
              <h3 className="text-sm font-medium">Chunks</h3>
              {current?.status !== "ready" ? (
                <p className="text-sm text-muted-foreground">
                  Chunks appear when the current version is ready.
                </p>
              ) : (
                <>
                  <Input
                    aria-label="Filter chunks"
                    placeholder="Filter chunks"
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                  />
                  <p className="text-xs text-muted-foreground">
                    {shownChunks.length} of {chunks.data?.length ?? 0} chunks
                  </p>
                  {shownChunks.map((chunk) => (
                    <div
                      key={chunk.position}
                      className="rounded-md border p-3 text-sm"
                    >
                      <div className="mb-1 text-xs text-muted-foreground">
                        #{chunk.position} · {chunk.modality}
                        {chunk.page !== null && ` · page ${chunk.page}`}
                        {chunk.heading_path.length > 0 &&
                          ` · ${chunk.heading_path.join(" › ")}`}
                      </div>
                      <pre className="font-sans whitespace-pre-wrap">
                        {chunk.text}
                      </pre>
                    </div>
                  ))}
                </>
              )}
            </section>
            <Separator />
            <section className="flex gap-2">
              {doc.deleted_at ? (
                <Button
                  disabled={restore.isPending}
                  onClick={() => restore.mutate()}
                >
                  Restore
                </Button>
              ) : (
                <Button variant="destructive" onClick={() => setDeleting(true)}>
                  Delete
                </Button>
              )}
            </section>
          </div>
        )}
        <PasswordDialog
          open={deleting}
          onOpenChange={setDeleting}
          title={`Delete ${doc?.filename ?? "document"}?`}
          description="It disappears from answers at once and can be restored for 30 days."
          confirmLabel="Delete document"
          destructive
          onConfirm={async (password) => {
            await adminApi.deleteDocument(documentId!, password)
            toast.success("Document deleted")
            refresh()
          }}
        />
      </SheetContent>
    </Sheet>
  )
}
