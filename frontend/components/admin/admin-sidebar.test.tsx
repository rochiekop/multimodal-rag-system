import { screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { AdminSidebar } from "@/components/admin/admin-sidebar"
import { SidebarProvider } from "@/components/ui/sidebar"
import { jsonResponse, renderWithProviders } from "@/test/render"

vi.mock("next/navigation", () => ({ usePathname: () => "/admin/users" }))
vi.mock("next-themes", () => ({
  useTheme: () => ({ theme: "light", setTheme: vi.fn() }),
}))

function mockApi(role: string, unread: unknown[] = []) {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input)
    if (url === "/api/auth/me")
      return jsonResponse({
        id: "u1",
        username: "ada",
        full_name: "Ada",
        role,
        is_active: true,
        must_change_password: false,
        groups: [],
      })
    if (url.startsWith("/api/admin/notifications")) return jsonResponse(unread)
    return jsonResponse({
      app_name: "Acme",
      primary_color: null,
      logo_url: null,
    })
  })
}

const renderSidebar = () =>
  renderWithProviders(
    <SidebarProvider>
      <AdminSidebar />
    </SidebarProvider>
  )

describe("AdminSidebar", () => {
  it("hides super-admin pages from admins and marks the current page", async () => {
    mockApi("admin", [{ id: "n1" }, { id: "n2" }])
    renderSidebar()
    const users = await screen.findByRole("link", { name: /Users & groups/ })
    expect(users).toHaveAttribute("data-active", "true")
    expect(screen.getByRole("link", { name: /Audit log/ })).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: /Settings/ })).toBeNull()
    expect(screen.queryByRole("link", { name: /Guardrails/ })).toBeNull()
    expect(await screen.findByLabelText("2 unread")).toBeInTheDocument()
  })

  it("shows super-admin pages to super admins", async () => {
    mockApi("super_admin")
    renderSidebar()
    expect(
      await screen.findByRole("link", { name: /Settings/ })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("link", { name: /Models & RAG config/ })
    ).toBeInTheDocument()
  })
})
