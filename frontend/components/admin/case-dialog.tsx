"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useState } from "react"
import { Controller, useForm } from "react-hook-form"
import { z } from "zod"

import { GroupChecklist } from "@/components/admin/group-checklist"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Field,
  FieldDescription,
  FieldError,
  FieldLabel,
} from "@/components/ui/field"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { adminApi } from "@/lib/admin-api"
import { ApiError } from "@/lib/api"
import type { ExpectedSource } from "@/lib/types"

/** "doc-id" or "doc-id:page" per line. */
export function parseSources(text: string): ExpectedSource[] | null {
  const sources: ExpectedSource[] = []
  for (const line of text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)) {
    const match = /^([0-9a-f-]{36})(?::(\d+))?$/i.exec(line)
    if (!match) return null
    sources.push({ doc_id: match[1], page: match[2] ? Number(match[2]) : null })
  }
  return sources
}

const schema = z.object({
  question: z.string().trim().min(1, "Enter a question").max(4000),
  expected_answer: z.string().max(8000),
  sources: z
    .string()
    .refine(
      (v) => parseSources(v) !== null,
      "One document id per line, optionally :page"
    ),
  collection_ids: z.array(z.string()),
  run_as_group_ids: z
    .array(z.string())
    .min(1, "Pick at least one group to ask as"),
  unanswerable: z.boolean(),
})
type Values = z.infer<typeof schema>
const EMPTY: Values = {
  question: "",
  expected_answer: "",
  sources: "",
  collection_ids: [],
  run_as_group_ids: [],
  unanswerable: false,
}

export function CaseDialog({
  setId,
  open,
  onOpenChange,
}: {
  setId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const groups = useQuery({
    queryKey: ["admin", "groups"],
    queryFn: adminApi.groups,
    enabled: open,
  })
  const collections = useQuery({
    queryKey: ["admin", "collections"],
    queryFn: adminApi.collections,
    enabled: open,
  })
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: EMPTY,
  })
  // Reset the form on open; the error is cleared on submit (set-state-in-effect lint rule).
  useEffect(() => {
    if (open) form.reset(EMPTY)
  }, [open, form])
  const create = useMutation({
    mutationFn: (values: Values) =>
      adminApi.createCase(setId, {
        question: values.question,
        expected_answer: values.expected_answer.trim() || null,
        expected_sources: parseSources(values.sources) ?? [],
        collection_ids: values.collection_ids,
        run_as_group_ids: values.run_as_group_ids,
        unanswerable: values.unanswerable,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["admin", "eval-cases", setId],
      })
      void queryClient.invalidateQueries({
        queryKey: ["admin", "eval-set", setId],
      })
      onOpenChange(false)
    },
    onError: (e) =>
      setError(e instanceof ApiError ? e.message : "Could not add the case"),
  })
  const { errors } = form.formState
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setError(null)
        onOpenChange(next)
      }}
    >
      <DialogContent className="max-h-[90svh] overflow-y-auto">
        <form
          className="grid gap-4"
          onSubmit={form.handleSubmit((v) => {
            setError(null)
            create.mutate(v)
          })}
        >
          <DialogHeader>
            <DialogTitle>Add case</DialogTitle>
            <DialogDescription>
              The question is asked through the real pipeline with the chosen
              groups&apos; access.
            </DialogDescription>
          </DialogHeader>
          <Field data-invalid={!!errors.question}>
            <FieldLabel htmlFor="case-question">Question</FieldLabel>
            <Textarea
              id="case-question"
              rows={2}
              {...form.register("question")}
            />
            <FieldError errors={[errors.question]} />
          </Field>
          <Field>
            <FieldLabel htmlFor="case-expected">
              Expected answer (optional)
            </FieldLabel>
            <Textarea
              id="case-expected"
              rows={2}
              {...form.register("expected_answer")}
            />
          </Field>
          <Controller
            control={form.control}
            name="unanswerable"
            render={({ field }) => (
              <div className="flex items-center gap-2">
                <Checkbox
                  id="case-unanswerable"
                  checked={field.value}
                  onCheckedChange={(v) => field.onChange(v === true)}
                />
                <Label htmlFor="case-unanswerable">
                  The documents can&apos;t answer this
                </Label>
              </div>
            )}
          />
          <Field data-invalid={!!errors.sources}>
            <FieldLabel htmlFor="case-sources">
              Expected sources (optional)
            </FieldLabel>
            <Textarea
              id="case-sources"
              rows={2}
              placeholder="document-id:page"
              {...form.register("sources")}
            />
            <FieldDescription>
              One document id per line, optionally followed by :page.
            </FieldDescription>
            <FieldError errors={[errors.sources]} />
          </Field>
          <Field data-invalid={!!errors.run_as_group_ids}>
            <FieldLabel>Ask as members of</FieldLabel>
            <Controller
              control={form.control}
              name="run_as_group_ids"
              render={({ field }) => (
                <GroupChecklist
                  groups={groups.data ?? []}
                  value={field.value}
                  onChange={field.onChange}
                  idPrefix="case-group"
                />
              )}
            />
            <FieldError errors={[errors.run_as_group_ids]} />
          </Field>
          <Field>
            <FieldLabel>Limit to collections (optional)</FieldLabel>
            <Controller
              control={form.control}
              name="collection_ids"
              render={({ field }) => (
                <GroupChecklist
                  groups={(collections.data ?? []).map((c) => ({
                    id: c.id,
                    name: c.name,
                    description: "",
                  }))}
                  value={field.value}
                  onChange={field.onChange}
                  idPrefix="case-collection"
                  empty="No collections yet."
                />
              )}
            />
          </Field>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button type="submit" disabled={create.isPending}>
              Add case
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
