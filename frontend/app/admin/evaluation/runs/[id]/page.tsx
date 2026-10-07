"use client"

import { useQuery } from "@tanstack/react-query"
import type { ColumnDef } from "@tanstack/react-table"
import { useParams } from "next/navigation"

import { DataTable } from "@/components/admin/data-table"
import { PageHeader } from "@/components/admin/page-header"
import {
  METRIC_LABELS,
  RunStatusBadge,
  RunSummary,
} from "@/components/admin/run-summary"
import { adminApi } from "@/lib/admin-api"
import { traceUrl } from "@/lib/config"
import { formatDateTime, formatUsd } from "@/lib/format"
import type { EvalResult } from "@/lib/types"

const columns: ColumnDef<EvalResult>[] = [
  {
    accessorKey: "question",
    header: "Question",
    cell: ({ row }) => (
      <span className="line-clamp-3 max-w-sm">{row.original.question}</span>
    ),
  },
  { accessorKey: "outcome", header: "Outcome" },
  {
    id: "answer",
    header: "Answer",
    cell: ({ row }) => (
      <span className="line-clamp-3 max-w-md whitespace-pre-wrap">
        {row.original.error ?? row.original.answer}
      </span>
    ),
  },
  {
    id: "metrics",
    header: "Metrics",
    cell: ({ row }) => (
      <ul className="text-xs">
        {Object.entries(row.original.metrics)
          .filter(([, v]) => v !== null)
          .map(([k, v]) => (
            <li key={k}>
              {METRIC_LABELS[k] ?? k}: {(v as number).toFixed(2)}
            </li>
          ))}
      </ul>
    ),
  },
  {
    id: "latency",
    header: "Latency",
    cell: ({ row }) => `${row.original.latency_ms} ms`,
  },
  {
    id: "cost",
    header: "Cost",
    cell: ({ row }) => formatUsd(row.original.cost_usd),
  },
  {
    id: "trace",
    header: "Trace",
    cell: ({ row }) => {
      const url = traceUrl(row.original.trace_id)
      return url ? (
        <a className="underline" href={url} target="_blank" rel="noreferrer">
          Open
        </a>
      ) : (
        "—"
      )
    },
  },
]

export default function EvalRunPage() {
  const { id } = useParams<{ id: string }>()
  const { data, isError } = useQuery({
    queryKey: ["admin", "eval-run", id],
    queryFn: () => adminApi.evalRun(id),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === "queued" || status === "running" ? 5000 : false
    },
  })
  if (isError)
    return <p className="text-sm text-destructive">Could not load this run.</p>
  if (!data) return <p className="text-sm text-muted-foreground">Loading…</p>
  return (
    <>
      <PageHeader
        title={`Run ${formatDateTime(data.created_at)}`}
        description={`${data.case_count} cases · config ${data.rag_config_version ? `v${data.rag_config_version}` : "defaults"}`}
        actions={<RunStatusBadge status={data.status} />}
      />
      {data.error && (
        <p className="mb-4 text-sm text-destructive">{data.error}</p>
      )}
      {data.status === "completed" && <RunSummary summary={data.summary} />}
      <div className="mt-6">
        <DataTable
          columns={columns}
          data={data.results}
          getRowId={(r) => r.id}
          empty="No results yet."
        />
      </div>
    </>
  )
}
