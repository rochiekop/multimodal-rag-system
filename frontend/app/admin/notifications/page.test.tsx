import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import NotificationsPage from "@/app/admin/notifications/page"
import { jsonResponse, renderWithProviders } from "@/test/render"

const note = {
  id: "n1",
  kind: "strike_lock",
  title: "User bob was locked",
  body: "3 strikes in 24 hours",
  target_type: "user",
  target_id: "u2",
  created_at: "2026-10-08T10:00:00Z",
  read_at: null,
}

describe("NotificationsPage", () => {
  it("marks a notification as read", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input, init) =>
        init?.method === "POST"
          ? jsonResponse({ ...note, read_at: "2026-10-08T11:00:00Z" })
          : jsonResponse([note])
      )
    renderWithProviders(<NotificationsPage />)
    await userEvent.click(
      await screen.findByRole("button", { name: "Mark as read" })
    )
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([u, i]) =>
            String(u) === "/api/admin/notifications/n1/read" &&
            i?.method === "POST"
        )
      ).toBe(true)
    )
  })
})
