import { screen, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import AdminLayout from "@/app/admin/layout"
import { jsonResponse, renderWithProviders } from "@/test/render"

const replace = vi.fn()
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/admin",
}))

const me = (role: string) => ({
  id: "u1",
  username: "ada",
  full_name: "Ada L",
  role,
  is_active: true,
  must_change_password: false,
  groups: [],
})

function mockApi(role: string) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input)
    if (url === "/api/auth/me") return jsonResponse(me(role))
    if (url.startsWith("/api/admin/notifications")) return jsonResponse([])
    return jsonResponse({
      app_name: "Acme",
      primary_color: null,
      logo_url: null,
    })
  })
}

describe("AdminLayout", () => {
  it("sends non-admins to /app without rendering the page", async () => {
    const fetchMock = mockApi("user")
    renderWithProviders(
      <AdminLayout>
        <p>secret page</p>
      </AdminLayout>
    )
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/app"))
    expect(screen.queryByText("secret page")).toBeNull()
    expect(
      fetchMock.mock.calls.some(([u]) => String(u).startsWith("/api/admin"))
    ).toBe(false)
  })

  it("renders the console for admins", async () => {
    mockApi("admin")
    renderWithProviders(
      <AdminLayout>
        <p>admin page</p>
      </AdminLayout>
    )
    expect(await screen.findByText("admin page")).toBeInTheDocument()
  })
})
