"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { toast } from "sonner"

import { Markdown } from "@/components/chat/markdown"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Field, FieldLabel } from "@/components/ui/field"
import { Label } from "@/components/ui/label"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import { Separator } from "@/components/ui/separator"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Textarea } from "@/components/ui/textarea"
import { adminApi } from "@/lib/admin-api"
import { ApiError } from "@/lib/api"
import { traceUrl } from "@/lib/config"
import { formatDateTime } from "@/lib/format"

/** One answer under review. Opening it is audited by the backend (spec §6.6). */
export function ReviewSheet({
  messageId,
  onOpenChange,
}: {
  messageId: string | null
  onOpenChange: (open: boolean) => void
}) {
  const { data, isError } = useQuery({
    queryKey: ["admin", "review-message", messageId],
    queryFn: () => adminApi.reviewMessage(messageId!),
    enabled: !!messageId,
  })
  const sets = useQuery({
    queryKey: ["admin", "eval-sets"],
    queryFn: adminApi.evalSets,
    enabled: !!messageId,
  })
  const queryClient = useQueryClient()
  const [setId, setSetId] = useState("")
  const [expected, setExpected] = useState("")
  const [unanswerable, setUnanswerable] = useState(false)
  const add = useMutation({
    mutationFn: () =>
      adminApi.addToEvalSet(messageId!, {
        eval_set_id: setId,
        expected_answer: expected.trim() || null,
        unanswerable,
      }),
    onSuccess: () => {
      toast.success("Added to the test set")
      void queryClient.invalidateQueries({ queryKey: ["admin", "eval-sets"] })
      setExpected("")
      setUnanswerable(false)
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Could not add the case"),
  })
  const answer = data?.answer
  const trace = traceUrl(answer?.trace_id ?? null)

  return (
    <Sheet open={!!messageId} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-2xl">
        <SheetHeader>
          <SheetTitle>Answer review</SheetTitle>
          <SheetDescription>
            {data
              ? `${data.user.username} · ${formatDateTime(data.answer.created_at)}`
              : ""}
          </SheetDescription>
        </SheetHeader>
        {isError && (
          <p className="px-4 text-sm text-destructive">
            Could not load this answer.
          </p>
        )}
        {data && answer && (
          <div className="grid gap-4 px-4 pb-6 text-sm">
            <section>
              <h3 className="mb-1 font-medium">Question</h3>
              <p className="whitespace-pre-wrap">{data.question ?? "—"}</p>
            </section>
            <section>
              <h3 className="mb-1 font-medium">Answer</h3>
              <div className="mb-2 flex flex-wrap gap-1">
                {answer.outcome && (
                  <Badge variant="outline">{answer.outcome}</Badge>
                )}
                {answer.low_confidence && (
                  <Badge variant="destructive">Low confidence</Badge>
                )}
                {answer.feedback_rating === -1 && (
                  <Badge variant="destructive">👎</Badge>
                )}
                {answer.feedback_rating === 1 && (
                  <Badge variant="secondary">👍</Badge>
                )}
              </div>
              <Markdown
                content={answer.content}
                sources={answer.citations}
                onOpenSource={() => {}}
              />
              {answer.feedback_comment && (
                <p className="mt-2 text-muted-foreground">
                  Comment: {answer.feedback_comment}
                </p>
              )}
            </section>
            {answer.sources.length > 0 && (
              <section>
                <h3 className="mb-1 font-medium">Sources</h3>
                <ol className="list-decimal pl-5">
                  {answer.sources.map((s) => (
                    <li key={`${s.n}-${s.doc_id}`}>
                      {s.filename}
                      {s.page !== null && `, page ${s.page}`} · score{" "}
                      {s.score.toFixed(2)}
                    </li>
                  ))}
                </ol>
              </section>
            )}
            {answer.guardrail && (
              <section>
                <h3 className="mb-1 font-medium">Guardrail</h3>
                <pre className="overflow-x-auto rounded-md bg-muted p-2 text-xs">
                  {JSON.stringify(answer.guardrail, null, 2)}
                </pre>
              </section>
            )}
            <p className="text-muted-foreground">
              Trace:{" "}
              {trace ? (
                <a
                  className="underline"
                  href={trace}
                  target="_blank"
                  rel="noreferrer"
                >
                  open in Phoenix
                </a>
              ) : (
                (answer.trace_id ?? "—")
              )}
            </p>
            <Separator />
            <form
              className="grid gap-3"
              onSubmit={(e) => {
                e.preventDefault()
                add.mutate()
              }}
            >
              <h3 className="font-medium">Add to a test set</h3>
              <Field>
                <FieldLabel htmlFor="review-set">Test set</FieldLabel>
                <NativeSelect
                  id="review-set"
                  value={setId}
                  onChange={(e) => setSetId(e.target.value)}
                >
                  <NativeSelectOption value="">
                    Choose a test set
                  </NativeSelectOption>
                  {sets.data?.map((s) => (
                    <NativeSelectOption key={s.id} value={s.id}>
                      {s.name}
                    </NativeSelectOption>
                  ))}
                </NativeSelect>
              </Field>
              <Field>
                <FieldLabel htmlFor="review-expected">
                  Expected answer
                </FieldLabel>
                <Textarea
                  id="review-expected"
                  rows={3}
                  value={expected}
                  onChange={(e) => setExpected(e.target.value)}
                />
              </Field>
              <div className="flex items-center gap-2">
                <Checkbox
                  id="review-unanswerable"
                  checked={unanswerable}
                  onCheckedChange={(v) => setUnanswerable(v === true)}
                />
                <Label htmlFor="review-unanswerable">
                  The documents can&apos;t answer this (expect &ldquo;I
                  don&apos;t know&rdquo;)
                </Label>
              </div>
              <div>
                <Button type="submit" disabled={!setId || add.isPending}>
                  Add to test set
                </Button>
              </div>
            </form>
          </div>
        )}
      </SheetContent>
    </Sheet>
  )
}
