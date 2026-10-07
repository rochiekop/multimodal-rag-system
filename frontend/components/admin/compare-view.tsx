"use client"

import { useQuery } from "@tanstack/react-query"
import { useState } from "react"

import { METRIC_LABELS } from "@/components/admin/run-summary"
import { Badge } from "@/components/ui/badge"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { adminApi } from "@/lib/admin-api"
import { cn } from "@/lib/utils"

// For these, lower is better.
const LOWER_IS_BETTER = new Set(["latency_p95_ms", "cost_per_question_usd"])

export function CompareView({
  a,
  b,
}: {
  a: string | undefined
  b: string | undefined
}) {
  const [onlyRegressions, setOnlyRegressions] = useState(false)
  const { data, isError } = useQuery({
    queryKey: ["admin", "compare", a, b],
    queryFn: () => adminApi.compareRuns(a!, b!),
    enabled: !!a && !!b,
  })
  if (!a || !b)
    return (
      <p className="text-sm text-muted-foreground">
        Pick two runs to compare on the Runs tab.
      </p>
    )
  if (isError)
    return (
      <p className="text-sm text-destructive">Could not compare these runs.</p>
    )
  if (!data) return <p className="text-sm text-muted-foreground">Loading…</p>
  const questions = data.questions.filter(
    (q) => !onlyRegressions || q.regressed
  )
  return (
    <div className="grid gap-6">
      <div className="overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader className="bg-muted">
            <TableRow>
              <TableHead>Metric</TableHead>
              <TableHead>Change (B − A)</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {Object.entries(data.deltas).map(([key, delta]) => {
              const worse = LOWER_IS_BETTER.has(key) ? delta > 0 : delta < 0
              return (
                <TableRow key={key}>
                  <TableCell>{METRIC_LABELS[key] ?? key}</TableCell>
                  <TableCell
                    className={cn("tabular-nums", worse && "text-destructive")}
                  >
                    {delta > 0 ? "+" : ""}
                    {delta.toFixed(
                      Math.abs(delta) < 0.01 && delta !== 0 ? 4 : 2
                    )}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </div>
      <div className="flex items-center gap-2">
        <Switch
          id="only-regressions"
          checked={onlyRegressions}
          onCheckedChange={setOnlyRegressions}
        />
        <Label htmlFor="only-regressions">Only regressions</Label>
      </div>
      <div className="overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader className="bg-muted">
            <TableRow>
              <TableHead>Question</TableHead>
              <TableHead>A</TableHead>
              <TableHead>B</TableHead>
              <TableHead>Regression</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {questions.map((q) => (
              <TableRow
                key={q.case_id}
                className={q.regressed ? "bg-destructive/5" : undefined}
              >
                <TableCell className="max-w-xs align-top">
                  {q.question}
                </TableCell>
                <TableCell className="max-w-sm align-top">
                  <Badge variant="outline">{q.a.outcome}</Badge>
                  <p className="mt-1 line-clamp-4 text-xs whitespace-pre-wrap">
                    {q.a.answer}
                  </p>
                </TableCell>
                <TableCell className="max-w-sm align-top">
                  <Badge variant="outline">{q.b.outcome}</Badge>
                  <p className="mt-1 line-clamp-4 text-xs whitespace-pre-wrap">
                    {q.b.answer}
                  </p>
                </TableCell>
                <TableCell className="align-top">
                  {q.reasons.map((r) => (
                    <p key={r} className="text-destructive">
                      {r}
                    </p>
                  ))}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
