import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { formatPercent, formatUsd } from "@/lib/format"
import type { RunStatus, RunSummary as Summary } from "@/lib/types"

export const METRIC_LABELS: Record<string, string> = {
  score: "Score",
  hit_rate: "Hit rate",
  context_precision: "Context precision",
  context_recall: "Context recall",
  faithfulness: "Faithfulness",
  answer_relevancy: "Answer relevance",
  answer_correctness: "Correctness",
  idk_accuracy: "“I don’t know” accuracy",
  answered_rate: "Answered rate",
  latency_p95_ms: "Latency p95 (ms)",
  cost_per_question_usd: "Cost / question",
}

export function RunStatusBadge({ status }: { status: RunStatus }) {
  const variant =
    status === "failed"
      ? "destructive"
      : status === "completed"
        ? "secondary"
        : "outline"
  return <Badge variant={variant}>{status}</Badge>
}

export function RunSummary({ summary }: { summary: Summary }) {
  const cards: [string, string][] = [
    ["Score", formatPercent(summary.score)],
    ...Object.entries(summary.metrics ?? {}).map(
      ([key, value]): [string, string] => [
        METRIC_LABELS[key] ?? key,
        formatPercent(value),
      ]
    ),
    [METRIC_LABELS.idk_accuracy, formatPercent(summary.idk_accuracy)],
    [METRIC_LABELS.answered_rate, formatPercent(summary.answered_rate)],
    [
      "Latency p50 / p95",
      `${summary.latency_p50_ms ?? "—"} / ${summary.latency_p95_ms ?? "—"} ms`,
    ],
    [
      "Cost / question",
      summary.cost_per_question_usd == null
        ? "—"
        : formatUsd(summary.cost_per_question_usd),
    ],
    ["Errors", String(summary.errors ?? 0)],
  ]
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {cards.map(([label, value]) => (
        <Card key={label}>
          <CardHeader>
            <CardDescription>{label}</CardDescription>
            <CardTitle className="text-xl tabular-nums">{value}</CardTitle>
          </CardHeader>
        </Card>
      ))}
    </div>
  )
}
