import { QueryClient } from "@tanstack/react-query"
import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { SidebarProvider } from "@/components/ui/sidebar"
import { UserMenu } from "@/components/user-menu"
import { navigateTo } from "@/lib/navigate"
import { jsonResponse, renderWithProviders } from "@/test/render"

vi.mock("@/lib/navigate", () => ({ navigateTo: vi.fn() }))
vi.mock("next-themes", () => ({
  useTheme: () => ({ theme: "light", setTheme: vi.fn() }),
}))

describe("UserMenu", () => {
  it("signs out, clears the query cache and navigates to /login", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input, init) =>
        init?.method === "DELETE"
          ? jsonResponse(null, 204)
          : jsonResponse({
              id: "u1",
              username: "ada",
              full_name: "Ada L",
              must_change_password: false,
            })
      )
    const clear = vi.spyOn(QueryClient.prototype, "clear")
    renderWithProviders(
      <SidebarProvider>
        <UserMenu />
      </SidebarProvider>
    )
    await screen.findByText("Ada L")
    await userEvent.click(screen.getByRole("button", { name: "Account menu" }))
    await userEvent.click(
      await screen.findByRole("menuitem", { name: "Sign out" })
    )
    await waitFor(() => expect(navigateTo).toHaveBeenCalledWith("/login"))
    expect(
      fetchMock.mock.calls.some(
        ([u, i]) => String(u) === "/api/auth/session" && i?.method === "DELETE"
      )
    ).toBe(true)
    expect(clear).toHaveBeenCalled()
  })
})
