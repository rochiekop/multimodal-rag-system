"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import type { ColumnDef } from "@tanstack/react-table"
import { useState } from "react"
import { toast } from "sonner"

import { DataTable } from "@/components/admin/data-table"
import { PageHeader } from "@/components/admin/page-header"
import { ReviewSheet } from "@/components/admin/review-sheet"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { adminApi } from "@/lib/admin-api"
import { ApiError } from "@/lib/api"
import { formatDateTime } from "@/lib/format"
import type { ReviewItem, ReviewKind } from "@/lib/types"

const KIND_LABELS: Record<ReviewKind, string> = {
  feedback: "👎 Feedback",
  low_confidence: "Low confidence",
  guardrail: "Guardrail",
}
const PAGE = 50

function summary(item: ReviewItem): string {
  const d = item.detail
  if (item.kind === "feedback") return String(d.comment ?? "No comment")
  if (item.kind === "guardrail")
    return [d.check, d.category, d.action]
      .filter(Boolean)
      .map(String)
      .join(" · ")
  return "Answer may not be supported by its sources"
}

export default function ReviewPage() {
  const queryClient = useQueryClient()
  const [kind, setKind] = useState<ReviewKind | "all">("all")
  const [includeReviewed, setIncludeReviewed] = useState(false)
  const [page, setPage] = useState(0)
  const [openMessage, setOpenMessage] = useState<string | null>(null)
  const queue = useQuery({
    queryKey: ["admin", "review", kind, includeReviewed, page],
    queryFn: () =>
      adminApi.reviewQueue(
        kind === "all" ? undefined : kind,
        includeReviewed,
        page * PAGE
      ),
  })
  const mark = useMutation({
    mutationFn: (item: ReviewItem) => adminApi.markReviewed(item.kind, item.id),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["admin", "review"] }),
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Could not update"),
  })

  const columns: ColumnDef<ReviewItem>[] = [
    {
      id: "when",
      header: "When",
      cell: ({ row }) => formatDateTime(row.original.created_at),
    },
    {
      id: "kind",
      header: "Kind",
      cell: ({ row }) => (
        <Badge variant="outline">{KIND_LABELS[row.original.kind]}</Badge>
      ),
    },
    { accessorKey: "username", header: "User" },
    {
      id: "question",
      header: "Question",
      cell: ({ row }) => (
        <span className="line-clamp-2 max-w-sm">
          {row.original.question ?? "—"}
        </span>
      ),
    },
    {
      id: "detail",
      header: "Detail",
      cell: ({ row }) => summary(row.original),
    },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => (
        <div className="flex gap-2">
          {row.original.message_id && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => setOpenMessage(row.original.message_id)}
            >
              Open
            </Button>
          )}
          {!row.original.reviewed_at && (
            <Button
              size="sm"
              variant="ghost"
              disabled={mark.isPending}
              onClick={() => mark.mutate(row.original)}
            >
              Mark reviewed
            </Button>
          )}
        </div>
      ),
    },
  ]

  return (
    <>
      <PageHeader
        title="Review queue"
        description="👎 answers, low-confidence answers and guardrail flags. Opening an answer is audited."
      />
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <Tabs
          value={kind}
          onValueChange={(value) => {
            setKind(value as ReviewKind | "all")
            setPage(0)
          }}
        >
          <TabsList>
            <TabsTrigger value="all">All</TabsTrigger>
            {(Object.keys(KIND_LABELS) as ReviewKind[]).map((k) => (
              <TabsTrigger key={k} value={k}>
                {KIND_LABELS[k]}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <div className="flex items-center gap-2">
          <Switch
            id="include-reviewed"
            checked={includeReviewed}
            onCheckedChange={(v) => {
              setIncludeReviewed(v)
              setPage(0)
            }}
          />
          <Label htmlFor="include-reviewed">Include reviewed</Label>
        </div>
      </div>
      <DataTable
        columns={columns}
        data={queue.data ?? []}
        isLoading={queue.isLoading}
        getRowId={(i) => `${i.kind}-${i.id}`}
        empty="Nothing to review."
      />
      <div className="mt-3 flex justify-end gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={page === 0}
          onClick={() => setPage(page - 1)}
        >
          Previous
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={(queue.data?.length ?? 0) < PAGE}
          onClick={() => setPage(page + 1)}
        >
          Next
        </Button>
      </div>
      <ReviewSheet
        key={openMessage ?? "none"}
        messageId={openMessage}
        onOpenChange={(open) => !open && setOpenMessage(null)}
      />
    </>
  )
}
