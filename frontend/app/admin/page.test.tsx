import { screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import DashboardPage from "@/app/admin/page"
import { jsonResponse, renderWithProviders } from "@/test/render"

vi.mock("@/components/admin/questions-chart", () => ({
  QuestionsChart: () => <div data-testid="chart" />,
}))

const dashboard = {
  days: 30,
  totals: {
    questions: 1234,
    active_users: 56,
    input_tokens: 1000,
    output_tokens: 500,
    cost_usd: 12.5,
    thumbs_up_rate: 0.8,
    not_found_rate: null,
    low_confidence_rate: 0.05,
    guardrail_blocks: 3,
  },
  daily: [],
  ingestion: { queued: 2, parsing: 1, ready: 40, failed: 1, rejected: 0 },
  health: { database: "ok", qdrant: "error", redis: "ok" },
}

describe("DashboardPage", () => {
  it("shows the figures, ingestion and health", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      jsonResponse(dashboard)
    )
    renderWithProviders(<DashboardPage />)
    expect(await screen.findByText("1,234")).toBeInTheDocument()
    expect(screen.getByText("80%")).toBeInTheDocument()
    expect(screen.getByText("$12.50")).toBeInTheDocument()
    expect(screen.getByText("—")).toBeInTheDocument() // no "I don't know" rate yet
    expect(screen.getByText("3 in progress")).toBeInTheDocument()
    expect(screen.getByText("1 failed")).toBeInTheDocument()
    expect(screen.getByText("Qdrant: error")).toBeInTheDocument()
  })
})
