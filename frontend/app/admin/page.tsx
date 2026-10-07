"use client"

import { useQuery } from "@tanstack/react-query"
import { useState } from "react"

import { PageHeader } from "@/components/admin/page-header"
import { QuestionsChart } from "@/components/admin/questions-chart"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import { adminApi } from "@/lib/admin-api"
import { formatPercent, formatUsd } from "@/lib/format"

const IN_PROGRESS = [
  "queued",
  "scanning",
  "parsing",
  "enriching",
  "chunking",
  "embedding",
  "indexing",
]
const SERVICES: Record<string, string> = {
  database: "Database",
  qdrant: "Qdrant",
  redis: "Redis",
}

export default function DashboardPage() {
  const [days, setDays] = useState(30)
  const { data, isError } = useQuery({
    queryKey: ["admin", "dashboard", days],
    queryFn: () => adminApi.dashboard(days),
    refetchInterval: 60_000,
  })

  const t = data?.totals
  const cards: [string, string][] = t
    ? [
        ["Questions", t.questions.toLocaleString("en-US")],
        ["Active users", t.active_users.toLocaleString("en-US")],
        ["Cost", formatUsd(t.cost_usd)],
        ["Tokens", (t.input_tokens + t.output_tokens).toLocaleString("en-US")],
        ["👍 rate", formatPercent(t.thumbs_up_rate)],
        ["“I don’t know” rate", formatPercent(t.not_found_rate)],
        ["Low-confidence rate", formatPercent(t.low_confidence_rate)],
        ["Guardrail blocks", t.guardrail_blocks.toLocaleString("en-US")],
      ]
    : []
  const inProgress = data
    ? IN_PROGRESS.reduce(
        (sum, status) => sum + (data.ingestion[status] ?? 0),
        0
      )
    : 0

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Usage and answer quality across the installation."
        actions={
          <NativeSelect
            aria-label="Period"
            value={String(days)}
            onChange={(e) => setDays(Number(e.target.value))}
          >
            <NativeSelectOption value="7">Last 7 days</NativeSelectOption>
            <NativeSelectOption value="30">Last 30 days</NativeSelectOption>
            <NativeSelectOption value="90">Last 90 days</NativeSelectOption>
          </NativeSelect>
        }
      />
      {isError && (
        <p className="text-sm text-destructive">
          Could not load the dashboard.
        </p>
      )}
      {data && (
        <div className="grid gap-4">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {cards.map(([label, value]) => (
              <Card key={label}>
                <CardHeader>
                  <CardDescription>{label}</CardDescription>
                  <CardTitle className="text-2xl tabular-nums">
                    {value}
                  </CardTitle>
                </CardHeader>
              </Card>
            ))}
          </div>
          <Card>
            <CardHeader>
              <CardTitle>Questions per day</CardTitle>
              <CardDescription>
                With answers the documents didn&apos;t cover.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <QuestionsChart data={data.daily} />
            </CardContent>
          </Card>
          <div className="grid gap-4 md:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Ingestion</CardTitle>
                <CardDescription>Document versions by status.</CardDescription>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-2">
                <Badge variant="secondary">{inProgress} in progress</Badge>
                <Badge variant="secondary">
                  {data.ingestion.ready ?? 0} ready
                </Badge>
                <Badge
                  variant={data.ingestion.failed ? "destructive" : "secondary"}
                >
                  {data.ingestion.failed ?? 0} failed
                </Badge>
                <Badge variant="secondary">
                  {data.ingestion.rejected ?? 0} rejected
                </Badge>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Service health</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-2">
                {Object.entries(data.health).map(([service, state]) => (
                  <Badge
                    key={service}
                    variant={state === "ok" ? "secondary" : "destructive"}
                  >
                    {SERVICES[service] ?? service}: {state}
                  </Badge>
                ))}
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </>
  )
}
