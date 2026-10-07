"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import type { ColumnDef } from "@tanstack/react-table"
import { UploadIcon } from "lucide-react"
import { useRef, useState } from "react"
import { toast } from "sonner"

import { DataTable } from "@/components/admin/data-table"
import {
  DocumentSheet,
  StatusBadge,
  isProcessing,
  latestVersion,
} from "@/components/admin/document-sheet"
import { PageHeader } from "@/components/admin/page-header"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import { Switch } from "@/components/ui/switch"
import { adminApi } from "@/lib/admin-api"
import { ApiError } from "@/lib/api"
import { formatBytes, formatDateTime } from "@/lib/format"
import type { AdminDocument, UploadResult } from "@/lib/types"

// Mirrors backend/app/documents/filetypes.py EXTENSIONS.
const ACCEPT =
  ".pdf,.docx,.pptx,.xlsx,.csv,.md,.markdown,.txt,.html,.htm,.png,.jpg,.jpeg,.tif,.tiff"

export default function DocumentsPage() {
  const queryClient = useQueryClient()
  const fileInput = useRef<HTMLInputElement>(null)
  const collections = useQuery({
    queryKey: ["admin", "collections"],
    queryFn: adminApi.collections,
  })
  const [chosen, setChosen] = useState<string | null>(null)
  const collectionId = chosen ?? collections.data?.[0]?.id ?? null
  const collection = collections.data?.find((c) => c.id === collectionId)
  const [showDeleted, setShowDeleted] = useState(false)
  const [openId, setOpenId] = useState<string | null>(null)
  const [problems, setProblems] = useState<UploadResult[]>([])

  const documents = useQuery({
    queryKey: ["admin", "documents", collectionId, showDeleted],
    queryFn: () => adminApi.documents(collectionId!, showDeleted),
    enabled: !!collectionId,
    refetchInterval: (query) =>
      query.state.data?.some((d) => isProcessing(latestVersion(d).status))
        ? 5000
        : false,
  })

  const upload = useMutation({
    mutationFn: (files: File[]) =>
      adminApi.uploadDocuments(collectionId!, files),
    onSuccess: (results) => {
      const queued = results.filter((r) => r.outcome === "queued").length
      setProblems(results.filter((r) => r.outcome !== "queued" || r.message))
      toast.success(
        `${queued} of ${results.length} files queued for processing`
      )
      void queryClient.invalidateQueries({ queryKey: ["admin", "documents"] })
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Upload failed"),
  })

  const columns: ColumnDef<AdminDocument>[] = [
    {
      accessorKey: "filename",
      header: "File",
      enableSorting: true,
      cell: ({ row }) => (
        <Button
          variant="link"
          className="h-auto p-0 font-medium"
          onClick={() => setOpenId(row.original.id)}
        >
          {row.original.filename}
        </Button>
      ),
    },
    {
      id: "status",
      header: "Status",
      cell: ({ row }) =>
        row.original.deleted_at ? (
          <span className="text-muted-foreground">Deleted</span>
        ) : (
          <StatusBadge status={latestVersion(row.original).status} />
        ),
    },
    {
      id: "chunks",
      header: "Chunks",
      cell: ({ row }) => latestVersion(row.original).chunk_count,
    },
    {
      id: "pages",
      header: "Pages",
      cell: ({ row }) => latestVersion(row.original).page_count ?? "—",
    },
    {
      id: "size",
      header: "Size",
      cell: ({ row }) => formatBytes(latestVersion(row.original).size_bytes),
    },
    {
      id: "access",
      header: "Access",
      cell: ({ row }) =>
        row.original.restricted_groups.length
          ? row.original.restricted_groups.map((g) => g.name).join(", ")
          : "Whole collection",
    },
    {
      id: "updated",
      header: "Updated",
      cell: ({ row }) => formatDateTime(latestVersion(row.original).updated_at),
    },
  ]

  return (
    <>
      <PageHeader
        title="Documents"
        description="Upload files; they are scanned, parsed and indexed in the background."
        actions={
          <>
            <NativeSelect
              aria-label="Collection"
              value={collectionId ?? ""}
              onChange={(e) => setChosen(e.target.value)}
            >
              {collections.data?.map((c) => (
                <NativeSelectOption key={c.id} value={c.id}>
                  {c.name}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <input
              ref={fileInput}
              type="file"
              multiple
              accept={ACCEPT}
              aria-label="Upload files"
              className="sr-only"
              onChange={(e) => {
                const files = Array.from(e.target.files ?? [])
                e.target.value = ""
                if (files.length) upload.mutate(files)
              }}
            />
            <Button
              disabled={!collectionId || upload.isPending}
              onClick={() => fileInput.current?.click()}
            >
              <UploadIcon /> {upload.isPending ? "Uploading…" : "Upload"}
            </Button>
          </>
        }
      />
      {collections.data?.length === 0 && (
        <p className="text-sm text-muted-foreground">
          Create a collection first (Collections &amp; access).
        </p>
      )}
      {problems.length > 0 && (
        <ul
          className="mb-4 grid gap-1 rounded-md border p-3 text-sm"
          aria-label="Upload problems"
        >
          {problems.map((p) => (
            <li key={p.filename}>
              {p.filename}: {p.message || p.outcome}
            </li>
          ))}
        </ul>
      )}
      <div className="mb-3 flex items-center gap-2">
        <Switch
          id="show-deleted"
          checked={showDeleted}
          onCheckedChange={setShowDeleted}
        />
        <Label htmlFor="show-deleted">Show deleted</Label>
      </div>
      <DataTable
        columns={columns}
        data={documents.data ?? []}
        isLoading={documents.isLoading && !!collectionId}
        getRowId={(d) => d.id}
        empty="No documents in this collection yet."
      />
      <DocumentSheet
        documentId={openId}
        collection={collection}
        onOpenChange={(open) => !open && setOpenId(null)}
      />
    </>
  )
}
