import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { CompareView } from "@/components/admin/compare-view"
import { jsonResponse, renderWithProviders } from "@/test/render"

const comparison = {
  a: { id: "r1", summary: { score: 0.9 } },
  b: { id: "r2", summary: { score: 0.7 } },
  deltas: { score: -0.2, faithfulness: -0.3 },
  questions: [
    {
      case_id: "k1",
      question: "Leave days?",
      a: { outcome: "answered", metrics: {}, answer: "25" },
      b: { outcome: "not_found", metrics: {}, answer: "I couldn't find it" },
      regressed: true,
      reasons: ["outcome answered → not_found"],
    },
    {
      case_id: "k2",
      question: "Office hours?",
      a: { outcome: "answered", metrics: {}, answer: "9-5" },
      b: { outcome: "answered", metrics: {}, answer: "9-5" },
      regressed: false,
      reasons: [],
    },
  ],
}

describe("CompareView", () => {
  it("highlights regressions and can show only them", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      jsonResponse(comparison)
    )
    renderWithProviders(<CompareView a="r1" b="r2" />)
    expect(
      await screen.findByText("outcome answered → not_found")
    ).toBeInTheDocument()
    expect(screen.getByText("-0.20")).toBeInTheDocument()
    expect(screen.getByText("Office hours?")).toBeInTheDocument()
    await userEvent.click(screen.getByLabelText("Only regressions"))
    expect(screen.queryByText("Office hours?")).toBeNull()
  })

  it("asks for two runs when one is missing", () => {
    renderWithProviders(<CompareView a={undefined} b="r2" />)
    expect(
      screen.getByText("Pick two runs to compare on the Runs tab.")
    ).toBeInTheDocument()
  })
})
