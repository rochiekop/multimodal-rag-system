import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import EvalSetPage from "@/app/admin/evaluation/sets/[id]/page"
import { jsonResponse, renderWithProviders } from "@/test/render"

vi.mock("next/navigation", () => ({ useParams: () => ({ id: "s1" }) }))

const hr = { id: "g1", name: "hr", description: "" }

function mockApi() {
  return vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith("/import"))
        return jsonResponse({
          created: 2,
          errors: [{ row: 4, message: "question: Field required" }],
        })
      if (url === "/api/admin/eval-sets/s1/cases" && init?.method === "POST")
        return jsonResponse({ id: "k9" }, 201)
      if (url === "/api/admin/eval-sets/s1")
        return jsonResponse({
          id: "s1",
          name: "Core",
          description: "",
          case_count: 0,
          created_at: "",
        })
      if (url === "/api/admin/groups") return jsonResponse([hr])
      return jsonResponse([])
    })
}

describe("EvalSetPage", () => {
  it("imports a CSV and shows row errors", async () => {
    mockApi()
    renderWithProviders(<EvalSetPage />)
    await screen.findByRole("heading", { name: "Core" })
    await userEvent.upload(
      screen.getByLabelText("Import CSV"),
      new File(["question\nA?\nB?\n,"], "cases.csv", { type: "text/csv" })
    )
    expect(await screen.findByText("2 cases imported")).toBeInTheDocument()
    expect(
      screen.getByText("Line 4: question: Field required")
    ).toBeInTheDocument()
  })

  it("adds an unanswerable case run as a group", async () => {
    const fetchMock = mockApi()
    renderWithProviders(<EvalSetPage />)
    await userEvent.click(
      await screen.findByRole("button", { name: "Add case" })
    )
    const dialog = await screen.findByRole("dialog")
    await userEvent.type(
      within(dialog).getByLabelText("Question"),
      "What is the CEO's salary?"
    )
    await userEvent.click(within(dialog).getByLabelText(/can't answer/))
    await userEvent.click(within(dialog).getByLabelText("hr"))
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Add case" })
    )
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([u, i]) =>
          String(u) === "/api/admin/eval-sets/s1/cases" && i?.method === "POST"
      )
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({
        question: "What is the CEO's salary?",
        expected_answer: null,
        expected_sources: [],
        collection_ids: [],
        run_as_group_ids: ["g1"],
        unanswerable: true,
      })
    })
  })
})
