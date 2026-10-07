"use client"

import { Area, AreaChart, CartesianGrid, XAxis } from "recharts"

import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"
import type { DailyPoint } from "@/lib/types"

const config = {
  questions: { label: "Questions", color: "var(--chart-1)" },
  not_found: { label: "I don't know", color: "var(--chart-2)" },
} satisfies ChartConfig

export function QuestionsChart({ data }: { data: DailyPoint[] }) {
  return (
    <ChartContainer config={config} className="aspect-auto h-64 w-full">
      <AreaChart data={data} margin={{ left: 12, right: 12 }}>
        <CartesianGrid vertical={false} />
        <XAxis
          dataKey="date"
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          minTickGap={24}
          tickFormatter={(value: string) => value.slice(5)}
        />
        <ChartTooltip content={<ChartTooltipContent indicator="dot" />} />
        {(["questions", "not_found"] as const).map((key) => (
          <Area
            key={key}
            dataKey={key}
            type="monotone"
            fill={`var(--color-${key})`}
            fillOpacity={0.3}
            stroke={`var(--color-${key})`}
          />
        ))}
      </AreaChart>
    </ChartContainer>
  )
}
