"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import type { ColumnDef } from "@tanstack/react-table"
import { useEffect, useMemo, useState } from "react"
import { useForm } from "react-hook-form"
import { toast } from "sonner"
import { z } from "zod"

import { ActivateDialog } from "@/components/admin/activate-dialog"
import { DataTable } from "@/components/admin/data-table"
import { PageHeader } from "@/components/admin/page-header"
import { SuperAdminOnly } from "@/components/admin/super-admin-only"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Field,
  FieldDescription,
  FieldError,
  FieldLabel,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import { Textarea } from "@/components/ui/textarea"
import { ApiError } from "@/lib/api"
import {
  useActiveConfig,
  useConfigVersions,
  useCreateVersion,
} from "@/lib/config-version"
import { formatDateTime, formatPercent } from "@/lib/format"
import {
  RERANKER_MODELS,
  type RagConfig,
  type RagConfigVersion,
} from "@/lib/types"

const PRICE_HINT =
  'JSON like {"gpt-5-mini": {"input_per_mtok": 0.25, "output_per_mtok": 2}}'

function parsePrices(text: string): RagConfig["prices"] | null {
  try {
    const value = JSON.parse(text)
    if (!value || typeof value !== "object" || Array.isArray(value)) return null
    for (const price of Object.values(value)) {
      const p = price as Record<string, unknown>
      if (
        typeof p?.input_per_mtok !== "number" ||
        typeof p?.output_per_mtok !== "number"
      )
        return null
    }
    return value
  } catch {
    return null
  }
}

const model = z.string().trim().min(1, "Enter a model name").max(100)
const schema = z.object({
  chat_model: model,
  rewrite_model: model,
  fallback_model: z.string().trim().max(100),
  eval_judge_model: model,
  reranker_model: z.enum(RERANKER_MODELS),
  search_top_k: z.number().int().min(1).max(200),
  rerank_top_n: z.number().int().min(1).max(30),
  rerank_threshold: z.number().min(0).max(1),
  history_turns: z.number().int().min(0).max(20),
  system_prompt: z.string().min(1).max(8000),
  rewrite_prompt: z.string().min(1).max(4000),
  not_found_message: z.string().min(1).max(500),
  greeting_message: z.string().min(1).max(500),
  prices: z.string().refine((v) => parsePrices(v) !== null, PRICE_HINT),
  note: z.string().max(500),
})
type Values = z.infer<typeof schema>

const toValues = (c: RagConfig): Values => ({
  chat_model: c.chat_model,
  rewrite_model: c.rewrite_model,
  fallback_model: c.fallback_model ?? "",
  eval_judge_model: c.eval_judge_model,
  reranker_model: c.reranker_model,
  search_top_k: c.search_top_k,
  rerank_top_n: c.rerank_top_n,
  rerank_threshold: c.rerank_threshold,
  history_turns: c.history_turns,
  system_prompt: c.system_prompt,
  rewrite_prompt: c.rewrite_prompt,
  not_found_message: c.not_found_message,
  greeting_message: c.greeting_message,
  prices: JSON.stringify(c.prices, null, 2),
  note: "",
})

const TEXT_FIELDS = [
  ["chat_model", "Chat model"],
  ["rewrite_model", "Rewrite model"],
  ["fallback_model", "Fallback model (optional)"],
  ["eval_judge_model", "Eval judge model"],
] as const
const NUMBER_FIELDS = [
  ["search_top_k", "Search top k", "1"],
  ["rerank_top_n", "Sources per answer", "1"],
  ["rerank_threshold", "Rerank threshold (0–1)", "0.01"],
  ["history_turns", "History turns", "1"],
] as const
const PROMPT_FIELDS = [
  ["system_prompt", "System prompt", 8],
  ["rewrite_prompt", "Rewrite prompt", 3],
  ["not_found_message", "“Not found” message", 2],
  ["greeting_message", "Reply to greetings (hello, hi…)", 2],
] as const

function ModelsEditor() {
  const active = useActiveConfig()
  const versions = useConfigVersions()
  const create = useCreateVersion()
  const [target, setTarget] = useState<RagConfigVersion | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const form = useForm<Values>({ resolver: zodResolver(schema) })
  const { errors } = form.formState

  useEffect(() => {
    if (active.data) form.reset(toValues(active.data.config))
  }, [active.data, form])

  async function onSubmit(values: Values) {
    if (!active.data) return
    setFormError(null)
    const { note, prices, fallback_model, ...rest } = values
    const config: RagConfig = {
      ...active.data.config,
      ...rest,
      fallback_model: fallback_model || null,
      prices: parsePrices(prices)!,
    }
    try {
      const saved = await create.mutateAsync({ config, note })
      toast.success(`Saved as v${saved.version}. Activate it to use it.`)
      form.setValue("note", "")
    } catch (error) {
      setFormError(
        error instanceof ApiError ? error.message : "Could not save. Try again."
      )
    }
  }

  // Memoized: DataTable renders `cell` functions as components, so a new identity per render
  // would remount (and detach) the buttons. The active version is read from the table rows.
  const columns = useMemo<ColumnDef<RagConfigVersion>[]>(
    () => [
      {
        id: "version",
        header: "Version",
        cell: ({ row }) => (
          <span className="flex items-center gap-2">
            v{row.original.version}
            {row.original.is_active && <Badge>Active</Badge>}
          </span>
        ),
      },
      { accessorKey: "note", header: "Note" },
      {
        id: "created",
        header: "Created",
        cell: ({ row }) => formatDateTime(row.original.created_at),
      },
      {
        id: "eval",
        header: "Latest eval",
        cell: ({ row }) =>
          row.original.latest_eval
            ? formatPercent(row.original.latest_eval.score)
            : "—",
      },
      {
        id: "actions",
        header: "",
        cell: ({ row, table }) =>
          row.original.is_active ? null : (
            <Button
              size="sm"
              variant="outline"
              aria-label={`Activate v${row.original.version}`}
              onClick={() => setTarget(row.original)}
            >
              {(table.getCoreRowModel().rows.find((r) => r.original.is_active)
                ?.original.version ?? 0) > row.original.version
                ? "Roll back"
                : "Activate"}
            </Button>
          ),
      },
    ],
    []
  )

  return (
    <div className="grid gap-6">
      <DataTable
        columns={columns}
        data={versions.data ?? []}
        isLoading={versions.isLoading}
        getRowId={(v) => v.id}
        empty="No versions yet; the defaults are in use."
      />
      <Card>
        <CardHeader>
          <CardTitle>New version</CardTitle>
        </CardHeader>
        <CardContent>
          {active.data && (
            <form className="grid gap-4" onSubmit={form.handleSubmit(onSubmit)}>
              <p className="text-sm text-muted-foreground">
                New versions start from the active configuration (
                {active.data.version ? `v${active.data.version}` : "defaults"}).
              </p>
              <div className="grid gap-4 md:grid-cols-2">
                {TEXT_FIELDS.map(([name, label]) => (
                  <Field key={name} data-invalid={!!errors[name]}>
                    <FieldLabel htmlFor={`cfg-${name}`}>{label}</FieldLabel>
                    <Input id={`cfg-${name}`} {...form.register(name)} />
                    <FieldError errors={[errors[name]]} />
                  </Field>
                ))}
                <Field>
                  <FieldLabel htmlFor="cfg-reranker">Reranker</FieldLabel>
                  <NativeSelect
                    id="cfg-reranker"
                    {...form.register("reranker_model")}
                  >
                    {RERANKER_MODELS.map((m) => (
                      <NativeSelectOption key={m} value={m}>
                        {m}
                      </NativeSelectOption>
                    ))}
                  </NativeSelect>
                </Field>
                {NUMBER_FIELDS.map(([name, label, step]) => (
                  <Field key={name} data-invalid={!!errors[name]}>
                    <FieldLabel htmlFor={`cfg-${name}`}>{label}</FieldLabel>
                    <Input
                      id={`cfg-${name}`}
                      type="number"
                      step={step}
                      {...form.register(name, { valueAsNumber: true })}
                    />
                    <FieldError errors={[errors[name]]} />
                  </Field>
                ))}
              </div>
              {PROMPT_FIELDS.map(([name, label, rows]) => (
                <Field key={name} data-invalid={!!errors[name]}>
                  <FieldLabel htmlFor={`cfg-${name}`}>{label}</FieldLabel>
                  <Textarea
                    id={`cfg-${name}`}
                    rows={rows}
                    {...form.register(name)}
                  />
                  <FieldError errors={[errors[name]]} />
                </Field>
              ))}
              <Field data-invalid={!!errors.prices}>
                <FieldLabel htmlFor="cfg-prices">
                  Prices (USD per million tokens)
                </FieldLabel>
                <Textarea
                  id="cfg-prices"
                  rows={6}
                  className="font-mono text-xs"
                  {...form.register("prices")}
                />
                <FieldDescription>
                  Every model used must have a price while cost caps are on.
                </FieldDescription>
                <FieldError errors={[errors.prices]} />
              </Field>
              <Field>
                <FieldLabel htmlFor="cfg-note">Note</FieldLabel>
                <Input id="cfg-note" {...form.register("note")} />
              </Field>
              {formError && (
                <p role="alert" className="text-sm text-destructive">
                  {formError}
                </p>
              )}
              <div>
                <Button type="submit" disabled={create.isPending}>
                  Save as new version
                </Button>
              </div>
            </form>
          )}
        </CardContent>
      </Card>
      <ActivateDialog
        target={target}
        versions={versions.data ?? []}
        onOpenChange={(open) => !open && setTarget(null)}
      />
    </div>
  )
}

export default function ModelsPage() {
  return (
    <>
      <PageHeader
        title="Models & RAG config"
        description="Every change is a new version. Compare eval scores, then activate or roll back."
      />
      <SuperAdminOnly>
        <ModelsEditor />
      </SuperAdminOnly>
    </>
  )
}
