"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import type { ColumnDef } from "@tanstack/react-table"
import Link from "next/link"
import { useState } from "react"
import { useForm } from "react-hook-form"
import { toast } from "sonner"
import { z } from "zod"

import { DataTable } from "@/components/admin/data-table"
import { PageHeader } from "@/components/admin/page-header"
import { RunStatusBadge } from "@/components/admin/run-summary"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Field, FieldError, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { adminApi } from "@/lib/admin-api"
import { api, ApiError } from "@/lib/api"
import { formatDateTime, formatPercent, formatUsd } from "@/lib/format"
import { isSuperAdmin } from "@/lib/roles"
import type { EvalRun, EvalSet } from "@/lib/types"

const setSchema = z.object({
  name: z.string().trim().min(1, "Enter a name").max(100),
  description: z.string().max(500),
})

function NewSetDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
}) {
  const queryClient = useQueryClient()
  const form = useForm<z.infer<typeof setSchema>>({
    resolver: zodResolver(setSchema),
    defaultValues: { name: "", description: "" },
  })
  const create = useMutation({
    mutationFn: adminApi.createEvalSet,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "eval-sets"] })
      form.reset()
      onOpenChange(false)
    },
    onError: (e) =>
      toast.error(
        e instanceof ApiError ? e.message : "Could not create the set"
      ),
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form
          className="grid gap-4"
          onSubmit={form.handleSubmit((v) => create.mutate(v))}
        >
          <DialogHeader>
            <DialogTitle>New test set</DialogTitle>
          </DialogHeader>
          <Field data-invalid={!!form.formState.errors.name}>
            <FieldLabel htmlFor="set-name">Name</FieldLabel>
            <Input id="set-name" {...form.register("name")} />
            <FieldError errors={[form.formState.errors.name]} />
          </Field>
          <Field>
            <FieldLabel htmlFor="set-description">Description</FieldLabel>
            <Input id="set-description" {...form.register("description")} />
          </Field>
          <DialogFooter>
            <Button type="submit" disabled={create.isPending}>
              Create
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export default function EvaluationPage() {
  const queryClient = useQueryClient()
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me })
  const superAdmin = !!me && isSuperAdmin(me)
  const sets = useQuery({
    queryKey: ["admin", "eval-sets"],
    queryFn: adminApi.evalSets,
  })
  const runs = useQuery({
    queryKey: ["admin", "eval-runs"],
    queryFn: () => adminApi.evalRuns(),
    refetchInterval: (query) =>
      query.state.data?.some(
        (r) => r.status === "queued" || r.status === "running"
      )
        ? 5000
        : false,
  })
  const versions = useQuery({
    queryKey: ["admin", "rag-configs"],
    queryFn: adminApi.ragConfigs,
    enabled: superAdmin,
  })
  const [newSet, setNewSet] = useState(false)
  const [setId, setSetId] = useState("")
  const [configId, setConfigId] = useState("")
  const [compareA, setCompareA] = useState("")
  const [compareB, setCompareB] = useState("")
  const setName = (id: string) =>
    sets.data?.find((s) => s.id === id)?.name ?? "—"

  const start = useMutation({
    mutationFn: () =>
      adminApi.startRun({
        eval_set_id: setId,
        rag_config_id: configId || null,
      }),
    onSuccess: () => {
      toast.success("Run queued")
      void queryClient.invalidateQueries({ queryKey: ["admin", "eval-runs"] })
    },
    onError: (e) =>
      toast.error(
        e instanceof ApiError ? e.message : "Could not start the run"
      ),
  })

  const setColumns: ColumnDef<EvalSet>[] = [
    {
      accessorKey: "name",
      header: "Name",
      enableSorting: true,
      cell: ({ row }) => (
        <Link
          className="font-medium underline-offset-4 hover:underline"
          href={`/admin/evaluation/sets/${row.original.id}`}
        >
          {row.original.name}
        </Link>
      ),
    },
    { accessorKey: "description", header: "Description" },
    { accessorKey: "case_count", header: "Cases" },
    {
      id: "created",
      header: "Created",
      cell: ({ row }) => formatDateTime(row.original.created_at),
    },
  ]
  const runColumns: ColumnDef<EvalRun>[] = [
    {
      id: "created",
      header: "Started",
      cell: ({ row }) => (
        <Link
          className="underline-offset-4 hover:underline"
          href={`/admin/evaluation/runs/${row.original.id}`}
        >
          {formatDateTime(row.original.created_at)}
        </Link>
      ),
    },
    {
      id: "set",
      header: "Test set",
      cell: ({ row }) => setName(row.original.eval_set_id),
    },
    {
      id: "config",
      header: "Config",
      cell: ({ row }) =>
        row.original.rag_config_version
          ? `v${row.original.rag_config_version}`
          : "defaults",
    },
    {
      id: "status",
      header: "Status",
      cell: ({ row }) => <RunStatusBadge status={row.original.status} />,
    },
    {
      id: "score",
      header: "Score",
      cell: ({ row }) => formatPercent(row.original.summary.score),
    },
    {
      id: "idk",
      header: "“I don’t know”",
      cell: ({ row }) => formatPercent(row.original.summary.idk_accuracy),
    },
    {
      id: "answered",
      header: "Answered",
      cell: ({ row }) => formatPercent(row.original.summary.answered_rate),
    },
    {
      id: "p95",
      header: "p95",
      cell: ({ row }) =>
        row.original.summary.latency_p95_ms == null
          ? "—"
          : `${row.original.summary.latency_p95_ms} ms`,
    },
    {
      id: "cost",
      header: "Cost / q",
      cell: ({ row }) =>
        row.original.summary.cost_per_question_usd == null
          ? "—"
          : formatUsd(row.original.summary.cost_per_question_usd),
    },
  ]
  const completed = (runs.data ?? []).filter((r) => r.status === "completed")
  const runLabel = (r: EvalRun) =>
    `${formatDateTime(r.created_at)} · ${setName(r.eval_set_id)} · ${r.rag_config_version ? `v${r.rag_config_version}` : "defaults"}`

  return (
    <>
      <PageHeader
        title="Evaluation"
        description="Test sets measure answer quality; compare runs before activating a config."
      />
      <Tabs defaultValue="sets">
        <TabsList>
          <TabsTrigger value="sets">Test sets</TabsTrigger>
          <TabsTrigger value="runs">Runs</TabsTrigger>
        </TabsList>
        <TabsContent value="sets" className="grid gap-3">
          <div className="flex justify-end">
            <Button onClick={() => setNewSet(true)}>New test set</Button>
          </div>
          <DataTable
            columns={setColumns}
            data={sets.data ?? []}
            isLoading={sets.isLoading}
            getRowId={(s) => s.id}
            empty="No test sets yet."
          />
        </TabsContent>
        <TabsContent value="runs" className="grid gap-4">
          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={(e) => {
              e.preventDefault()
              start.mutate()
            }}
          >
            <Field className="w-56">
              <FieldLabel htmlFor="run-set">Test set</FieldLabel>
              <NativeSelect
                id="run-set"
                value={setId}
                onChange={(e) => setSetId(e.target.value)}
              >
                <NativeSelectOption value="">
                  Choose a test set
                </NativeSelectOption>
                {sets.data?.map((s) => (
                  <NativeSelectOption key={s.id} value={s.id}>
                    {s.name} ({s.case_count})
                  </NativeSelectOption>
                ))}
              </NativeSelect>
            </Field>
            <Field className="w-56">
              <FieldLabel htmlFor="run-config">Configuration</FieldLabel>
              <NativeSelect
                id="run-config"
                value={configId}
                onChange={(e) => setConfigId(e.target.value)}
              >
                <NativeSelectOption value="">
                  Active configuration
                </NativeSelectOption>
                {versions.data?.map((v) => (
                  <NativeSelectOption key={v.id} value={v.id}>
                    v{v.version}
                    {v.is_active ? " (active)" : ""} {v.note && `– ${v.note}`}
                  </NativeSelectOption>
                ))}
              </NativeSelect>
            </Field>
            <Button type="submit" disabled={!setId || start.isPending}>
              Start run
            </Button>
          </form>
          <DataTable
            columns={runColumns}
            data={runs.data ?? []}
            isLoading={runs.isLoading}
            getRowId={(r) => r.id}
            empty="No runs yet."
          />
          <div className="flex flex-wrap items-end gap-3">
            <Field className="w-72">
              <FieldLabel htmlFor="compare-a">Baseline run (A)</FieldLabel>
              <NativeSelect
                id="compare-a"
                value={compareA}
                onChange={(e) => setCompareA(e.target.value)}
              >
                <NativeSelectOption value="">Choose a run</NativeSelectOption>
                {completed.map((r) => (
                  <NativeSelectOption key={r.id} value={r.id}>
                    {runLabel(r)}
                  </NativeSelectOption>
                ))}
              </NativeSelect>
            </Field>
            <Field className="w-72">
              <FieldLabel htmlFor="compare-b">Candidate run (B)</FieldLabel>
              <NativeSelect
                id="compare-b"
                value={compareB}
                onChange={(e) => setCompareB(e.target.value)}
              >
                <NativeSelectOption value="">Choose a run</NativeSelectOption>
                {completed.map((r) => (
                  <NativeSelectOption key={r.id} value={r.id}>
                    {runLabel(r)}
                  </NativeSelectOption>
                ))}
              </NativeSelect>
            </Field>
            {compareA && compareB && compareA !== compareB ? (
              <Button variant="outline" asChild>
                <Link
                  href={`/admin/evaluation/compare?a=${compareA}&b=${compareB}`}
                >
                  Compare
                </Link>
              </Button>
            ) : (
              <Button variant="outline" disabled>
                Compare
              </Button>
            )}
          </div>
        </TabsContent>
      </Tabs>
      <NewSetDialog open={newSet} onOpenChange={setNewSet} />
    </>
  )
}
