import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import EvaluationPage from "@/app/admin/evaluation/page"
import { jsonResponse, renderWithProviders } from "@/test/render"

const set = {
  id: "s1",
  name: "Core",
  description: "",
  case_count: 4,
  created_at: "2026-10-01T00:00:00Z",
}
const run = {
  id: "r1",
  eval_set_id: "s1",
  rag_config_id: null,
  rag_config_version: 2,
  status: "completed",
  error: null,
  case_count: 4,
  summary: {
    score: 0.82,
    idk_accuracy: 1,
    answered_rate: 0.75,
    latency_p95_ms: 2100,
    cost_per_question_usd: 0.003,
  },
  created_at: "2026-10-08T09:00:00Z",
  started_at: "2026-10-08T09:00:01Z",
  finished_at: "2026-10-08T09:02:00Z",
}

describe("EvaluationPage", () => {
  it("starts a run on the active config without listing versions for admins", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input, init) => {
        const url = String(input)
        if (url === "/api/auth/me")
          return jsonResponse({
            id: "u1",
            username: "a",
            full_name: "A",
            role: "admin",
            is_active: true,
            must_change_password: false,
            groups: [],
          })
        if (url === "/api/admin/eval-sets") return jsonResponse([set])
        if (init?.method === "POST")
          return jsonResponse({ ...run, id: "r2", status: "queued" }, 202)
        return jsonResponse([run])
      })
    renderWithProviders(<EvaluationPage />)
    await userEvent.click(await screen.findByRole("tab", { name: "Runs" }))
    expect(await screen.findByText("82%")).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText("Test set"), "s1")
    await userEvent.click(screen.getByRole("button", { name: "Start run" }))
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([u, i]) => String(u) === "/api/admin/eval-runs" && i?.method === "POST"
      )
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({
        eval_set_id: "s1",
        rag_config_id: null,
      })
    })
    expect(
      fetchMock.mock.calls.some(([u]) =>
        String(u).startsWith("/api/admin/rag-configs")
      )
    ).toBe(false)
  })
})
