import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import ReviewPage from "@/app/admin/review/page"
import { jsonResponse, renderWithProviders } from "@/test/render"

const item = {
  kind: "feedback",
  id: "m1",
  created_at: "2026-10-08T10:00:00Z",
  user_id: "u2",
  username: "bob",
  message_id: "m1",
  question: "How many leave days?",
  answer: "Twenty [1]",
  detail: { rating: -1, comment: "Wrong number" },
  reviewed_at: null,
}
const detail = {
  conversation_id: "c9",
  user: { id: "u2", username: "bob" },
  question: "How many leave days?",
  answer: {
    id: "m1",
    content: "Employees get **twenty** days <script>alert(1)</script>",
    outcome: "answered",
    sources: [],
    citations: [],
    low_confidence: false,
    guardrail: null,
    feedback_rating: -1,
    feedback_comment: "Wrong number",
    trace_id: "abc123",
    created_at: "2026-10-08T10:00:00Z",
  },
}

function mockApi() {
  return vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, init) => {
      const url = String(input)
      if (init?.method === "POST")
        return jsonResponse(null, url.endsWith("/reviewed") ? 204 : 201)
      if (url.startsWith("/api/admin/review-queue/messages/m1"))
        return jsonResponse(detail)
      if (url === "/api/admin/eval-sets")
        return jsonResponse([
          {
            id: "s1",
            name: "Core",
            description: "",
            case_count: 3,
            created_at: "",
          },
        ])
      return jsonResponse([item])
    })
}

describe("ReviewPage", () => {
  it("marks an item reviewed", async () => {
    const fetchMock = mockApi()
    renderWithProviders(<ReviewPage />)
    expect(await screen.findByText("Wrong number")).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Mark reviewed" }))
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([u, i]) =>
            String(u) === "/api/admin/review-queue/feedback/m1/reviewed" &&
            i?.method === "POST"
        )
      ).toBe(true)
    )
  })

  it("opens the conversation safely and adds it to a test set", async () => {
    const fetchMock = mockApi()
    renderWithProviders(<ReviewPage />)
    await userEvent.click(await screen.findByRole("button", { name: "Open" }))
    const sheet = await screen.findByRole("dialog")
    expect(await within(sheet).findByText("twenty")).toBeInTheDocument()
    expect(within(sheet).getByText("abc123")).toBeInTheDocument()
    expect(sheet.querySelector("script")).toBeNull()
    await userEvent.selectOptions(
      within(sheet).getByLabelText("Test set"),
      "s1"
    )
    await userEvent.type(
      within(sheet).getByLabelText("Expected answer"),
      "Twenty-five days"
    )
    await userEvent.click(
      within(sheet).getByRole("button", { name: "Add to test set" })
    )
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u]) =>
        String(u).endsWith("/add-to-eval-set")
      )
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({
        eval_set_id: "s1",
        expected_answer: "Twenty-five days",
        unanswerable: false,
      })
    })
  })
})
