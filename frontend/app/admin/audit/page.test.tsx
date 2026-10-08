import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import AuditPage from "@/app/admin/audit/page"
import { jsonResponse, renderWithProviders } from "@/test/render"

const entry = (id: number) => ({
  id,
  created_at: "2026-10-08T10:00:00Z",
  actor_id: "u1",
  actor_username: "root",
  action: "user.created",
  target_type: "user",
  target_id: `u${id}`,
  detail: { role: "user" },
  request_id: "req-1",
})

describe("AuditPage", () => {
  it("filters, pages back and exports with the same filters", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input) => {
        const url = String(input)
        if (url.includes("before_id=51")) return jsonResponse([entry(50)])
        if (url.includes("action=user."))
          return jsonResponse(
            Array.from({ length: 50 }, (_, i) => entry(100 - i))
          )
        return jsonResponse([entry(1)])
      })
    renderWithProviders(<AuditPage />)
    await screen.findByText("u1")
    await userEvent.type(screen.getByLabelText("Action starts with"), "user.")
    await userEvent.click(screen.getByRole("button", { name: "Apply" }))
    await screen.findByText("u100")
    expect(screen.getByRole("link", { name: "Export CSV" })).toHaveAttribute(
      "href",
      "/api/admin/audit/export?action=user."
    )
    await userEvent.click(
      screen.getByRole("button", { name: "Load older entries" })
    )
    await screen.findByText("u50")
    expect(
      fetchMock.mock.calls.some(
        ([u]) =>
          String(u) === "/api/admin/audit?action=user.&before_id=51&limit=50"
      )
    ).toBe(true)
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Load older entries" })
      ).toBeNull()
    )
  })
})
