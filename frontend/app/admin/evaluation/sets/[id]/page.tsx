"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import type { ColumnDef } from "@tanstack/react-table"
import { useParams } from "next/navigation"
import { useRef, useState } from "react"
import { toast } from "sonner"

import { CaseDialog } from "@/components/admin/case-dialog"
import { DataTable } from "@/components/admin/data-table"
import { PageHeader } from "@/components/admin/page-header"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { adminApi } from "@/lib/admin-api"
import { ApiError } from "@/lib/api"
import type { EvalCase, ImportResult } from "@/lib/types"

export default function EvalSetPage() {
  const { id } = useParams<{ id: string }>()
  const queryClient = useQueryClient()
  const fileInput = useRef<HTMLInputElement>(null)
  const [adding, setAdding] = useState(false)
  const [imported, setImported] = useState<ImportResult | null>(null)
  const set = useQuery({
    queryKey: ["admin", "eval-set", id],
    queryFn: () => adminApi.evalSet(id),
  })
  const cases = useQuery({
    queryKey: ["admin", "eval-cases", id],
    queryFn: () => adminApi.evalCases(id),
  })
  const refresh = () => {
    void queryClient.invalidateQueries({
      queryKey: ["admin", "eval-cases", id],
    })
    void queryClient.invalidateQueries({ queryKey: ["admin", "eval-set", id] })
    void queryClient.invalidateQueries({ queryKey: ["admin", "eval-sets"] })
  }
  const importCsv = useMutation({
    mutationFn: (file: File) => adminApi.importCases(id, file),
    onSuccess: (result) => {
      setImported(result)
      refresh()
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Import failed"),
  })
  const remove = useMutation({
    mutationFn: adminApi.deleteCase,
    onSuccess: refresh,
    onError: (e) =>
      toast.error(
        e instanceof ApiError ? e.message : "Could not delete the case"
      ),
  })

  const columns: ColumnDef<EvalCase>[] = [
    {
      accessorKey: "question",
      header: "Question",
      cell: ({ row }) => (
        <span className="line-clamp-3 max-w-md">{row.original.question}</span>
      ),
    },
    {
      id: "expected",
      header: "Expected",
      cell: ({ row }) =>
        row.original.unanswerable ? (
          <Badge variant="outline">Unanswerable</Badge>
        ) : (
          <span className="line-clamp-3 max-w-sm">
            {row.original.expected_answer ?? "—"}
          </span>
        ),
    },
    {
      id: "sources",
      header: "Sources",
      cell: ({ row }) => row.original.expected_sources.length || "—",
    },
    { accessorKey: "origin", header: "Origin" },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => (
        <Button
          size="sm"
          variant="ghost"
          disabled={remove.isPending}
          onClick={() => remove.mutate(row.original.id)}
        >
          Delete
        </Button>
      ),
    },
  ]

  return (
    <>
      <PageHeader
        title={set.data?.name ?? "Test set"}
        description={
          set.data?.description ||
          "Questions with expected answers and sources."
        }
        actions={
          <>
            <input
              ref={fileInput}
              type="file"
              accept=".csv,text/csv"
              aria-label="Import CSV"
              className="sr-only"
              onChange={(e) => {
                const file = e.target.files?.[0]
                e.target.value = ""
                if (file) importCsv.mutate(file)
              }}
            />
            <Button
              variant="outline"
              disabled={importCsv.isPending}
              onClick={() => fileInput.current?.click()}
            >
              Import CSV
            </Button>
            <Button onClick={() => setAdding(true)}>Add case</Button>
          </>
        }
      />
      {imported && (
        <div className="mb-4 rounded-md border p-3 text-sm" role="status">
          <p>{imported.created} cases imported</p>
          {imported.errors.length > 0 && (
            <ul className="mt-1 text-destructive">
              {imported.errors.map((e) => (
                <li key={e.row}>
                  Line {e.row}: {e.message}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      <p className="mb-3 text-xs text-muted-foreground">
        CSV columns: question, expected_answer, expected_sources
        (doc_id[:page];…), collections (names; …), groups (names; …),
        unanswerable.
      </p>
      <DataTable
        columns={columns}
        data={cases.data ?? []}
        isLoading={cases.isLoading}
        getRowId={(c) => c.id}
        empty="No cases yet."
      />
      <CaseDialog setId={id} open={adding} onOpenChange={setAdding} />
    </>
  )
}
