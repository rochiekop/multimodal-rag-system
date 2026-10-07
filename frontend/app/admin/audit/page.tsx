"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { useInfiniteQuery } from "@tanstack/react-query"
import type { ColumnDef } from "@tanstack/react-table"
import { DownloadIcon } from "lucide-react"
import { useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { DataTable } from "@/components/admin/data-table"
import { PageHeader } from "@/components/admin/page-header"
import { Button } from "@/components/ui/button"
import { Field, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { adminApi } from "@/lib/admin-api"
import { formatDateTime } from "@/lib/format"
import type { AuditEntry, AuditFilters } from "@/lib/types"

const PAGE = 50
const schema = z.object({
  actor: z.string().max(64),
  action: z.string().max(100),
  target_type: z.string().max(50),
  target_id: z.string().max(100),
  since: z.string(),
  until: z.string(),
})
type Values = z.infer<typeof schema>
const EMPTY: Values = {
  actor: "",
  action: "",
  target_type: "",
  target_id: "",
  since: "",
  until: "",
}

/** Local calendar days to an inclusive [since, until) range in UTC ISO strings. */
function toFilters(values: Values): AuditFilters {
  const filters: AuditFilters = {}
  for (const key of ["actor", "action", "target_type", "target_id"] as const) {
    const value = values[key].trim()
    if (value) filters[key] = value
  }
  if (values.since)
    filters.since = new Date(`${values.since}T00:00:00`).toISOString()
  if (values.until) {
    const end = new Date(`${values.until}T00:00:00`)
    end.setDate(end.getDate() + 1)
    filters.until = end.toISOString()
  }
  return filters
}

const columns: ColumnDef<AuditEntry>[] = [
  {
    id: "when",
    header: "When",
    cell: ({ row }) => formatDateTime(row.original.created_at),
  },
  {
    id: "actor",
    header: "Actor",
    cell: ({ row }) => row.original.actor_username ?? "system",
  },
  { accessorKey: "action", header: "Action" },
  {
    id: "target",
    header: "Target",
    cell: ({ row }) =>
      row.original.target_id ? (
        <span>
          <span className="text-muted-foreground">
            {row.original.target_type}
          </span>{" "}
          {row.original.target_id}
        </span>
      ) : (
        "—"
      ),
  },
  {
    id: "detail",
    header: "Details",
    cell: ({ row }) => (
      <code className="line-clamp-2 max-w-md text-xs break-all">
        {JSON.stringify(row.original.detail)}
      </code>
    ),
  },
  {
    id: "request",
    header: "Request",
    cell: ({ row }) => (
      <code className="text-xs text-muted-foreground">
        {row.original.request_id ?? "—"}
      </code>
    ),
  },
]

const LABELS: Record<keyof Values, string> = {
  actor: "Actor username",
  action: "Action starts with",
  target_type: "Target type",
  target_id: "Target id",
  since: "From",
  until: "To",
}

export default function AuditPage() {
  const [filters, setFilters] = useState<AuditFilters>({})
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: EMPTY,
  })
  const audit = useInfiniteQuery({
    queryKey: ["admin", "audit", filters],
    queryFn: ({ pageParam }) => adminApi.audit(filters, pageParam, PAGE),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) =>
      last.length === PAGE ? last[last.length - 1].id : undefined,
  })
  const rows = audit.data?.pages.flat() ?? []

  return (
    <>
      <PageHeader
        title="Audit log"
        description="Every sign-in, change and admin view. Entries can't be edited or deleted."
        actions={
          <Button variant="outline" asChild>
            <a href={adminApi.auditExportUrl(filters)} download>
              <DownloadIcon /> Export CSV
            </a>
          </Button>
        }
      />
      <form
        className="mb-4 grid gap-3 sm:grid-cols-3 lg:grid-cols-6"
        onSubmit={form.handleSubmit((values) => setFilters(toFilters(values)))}
      >
        {(Object.keys(LABELS) as (keyof Values)[]).map((key) => (
          <Field key={key}>
            <FieldLabel htmlFor={`audit-${key}`}>{LABELS[key]}</FieldLabel>
            <Input
              id={`audit-${key}`}
              type={key === "since" || key === "until" ? "date" : "text"}
              {...form.register(key)}
            />
          </Field>
        ))}
        <div className="flex gap-2 sm:col-span-3 lg:col-span-6">
          <Button type="submit">Apply</Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              form.reset(EMPTY)
              setFilters({})
            }}
          >
            Clear
          </Button>
        </div>
      </form>
      <DataTable
        columns={columns}
        data={rows}
        isLoading={audit.isLoading}
        getRowId={(e) => String(e.id)}
        empty="No entries match."
      />
      {audit.hasNextPage && (
        <div className="mt-3 flex justify-center">
          <Button
            variant="outline"
            disabled={audit.isFetchingNextPage}
            onClick={() => void audit.fetchNextPage()}
          >
            Load older entries
          </Button>
        </div>
      )}
    </>
  )
}
