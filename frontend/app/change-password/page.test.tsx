import { QueryClient } from "@tanstack/react-query"
import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import ChangePasswordPage from "@/app/change-password/page"
import { navigateTo } from "@/lib/navigate"
import { jsonResponse, renderWithProviders } from "@/test/render"

const replace = vi.fn()
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }))
vi.mock("@/lib/navigate", () => ({ navigateTo: vi.fn() }))

const user = {
  id: "u1",
  username: "alice",
  full_name: "Alice",
  role: "user",
  is_active: true,
  must_change_password: false,
  groups: [],
}

const newClient = () =>
  new QueryClient({ defaultOptions: { queries: { retry: false } } })

afterEach(() => vi.clearAllMocks())

describe("ChangePasswordPage", () => {
  it("updates the cached user before going to /app so the gate doesn't bounce back", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      jsonResponse({ must_change_password: false, user })
    )
    const client = newClient()
    client.setQueryData(["me"], { ...user, must_change_password: true })
    renderWithProviders(<ChangePasswordPage />, client)
    await userEvent.type(screen.getByLabelText("Current password"), "old-1234")
    await userEvent.type(screen.getByLabelText("New password"), "new-pass-456")
    await userEvent.type(
      screen.getByLabelText("Confirm new password"),
      "new-pass-456"
    )
    await userEvent.click(
      screen.getByRole("button", { name: "Change password" })
    )
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/app"))
    expect(client.getQueryData(["me"])).toEqual(user)
  })

  it("can sign out instead", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async () => jsonResponse(null, 204))
    const client = newClient()
    client.setQueryData(["me"], { ...user, must_change_password: true })
    renderWithProviders(<ChangePasswordPage />, client)
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }))
    await waitFor(() => expect(navigateTo).toHaveBeenCalledWith("/login"))
    expect(
      fetchMock.mock.calls.some(
        ([u, i]) => String(u) === "/api/auth/session" && i?.method === "DELETE"
      )
    ).toBe(true)
    expect(client.getQueryData(["me"])).toBeUndefined()
  })
})
