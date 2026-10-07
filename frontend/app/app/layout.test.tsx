import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import AppLayout from "@/app/app/layout"
import { jsonResponse, renderWithProviders } from "@/test/render"

const replace = vi.fn()
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/app",
}))

describe("AppLayout", () => {
  it("offers a retry when /me fails with a server error", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async () =>
        jsonResponse({ detail: { code: "boom", message: "Boom" } }, 500)
      )
    renderWithProviders(
      <AppLayout>
        <p>content</p>
      </AppLayout>
    )
    expect(
      await screen.findByText("Can't reach the server.")
    ).toBeInTheDocument()
    const meCalls = () =>
      fetchMock.mock.calls.filter(([u]) => String(u) === "/api/auth/me").length
    expect(meCalls()).toBe(1)
    await userEvent.click(screen.getByRole("button", { name: "Retry" }))
    await waitFor(() => expect(meCalls()).toBe(2))
    expect(screen.queryByText("content")).toBeNull()
    expect(replace).not.toHaveBeenCalled()
  })
})
