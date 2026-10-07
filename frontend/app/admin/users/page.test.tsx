import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import UsersPage from "@/app/admin/users/page"
import { jsonResponse, renderWithProviders } from "@/test/render"

const hr = { id: "g1", name: "hr", description: "" }
const bob = {
  id: "u2",
  username: "bob",
  full_name: "Bob B",
  role: "user",
  is_active: true,
  must_change_password: false,
  locked_until: null,
  chat_locked_until: "2999-01-01T00:00:00Z",
  groups: [hr],
  created_at: "2026-10-01T00:00:00Z",
}

function mockApi(myRole: string) {
  return vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, init) => {
      const url = String(input)
      if (url === "/api/auth/me")
        return jsonResponse({ ...bob, id: "u1", username: "me", role: myRole })
      if (init?.method === "POST" || init?.method === "PATCH")
        return jsonResponse(bob)
      if (url === "/api/admin/groups") return jsonResponse([hr])
      return jsonResponse([bob])
    })
}

const bodyOf = (
  fetchMock: ReturnType<typeof mockApi>,
  method: string,
  url: string
) => {
  const call = fetchMock.mock.calls.find(
    ([u, i]) => String(u) === url && i?.method === method
  )
  return call ? JSON.parse(String(call[1]?.body)) : undefined
}

describe("UsersPage", () => {
  it("shows a chat lock and unlocks the user", async () => {
    const fetchMock = mockApi("admin")
    renderWithProviders(<UsersPage />)
    expect(await screen.findByText("Chat locked")).toBeInTheDocument()
    await userEvent.click(
      screen.getByRole("button", { name: "Actions for bob" })
    )
    await userEvent.click(
      await screen.findByRole("menuitem", { name: "Unlock" })
    )
    await waitFor(() =>
      expect(bodyOf(fetchMock, "PATCH", "/api/admin/users/u2")).toEqual({
        unlock: true,
      })
    )
  })

  it("creates a user; only super admins can grant super_admin", async () => {
    const fetchMock = mockApi("admin")
    renderWithProviders(<UsersPage />)
    await userEvent.click(
      await screen.findByRole("button", { name: "New user" })
    )
    const dialog = await screen.findByRole("dialog")
    const role = within(dialog).getByLabelText("Role")
    expect(
      within(role).queryByRole("option", { name: "Super admin" })
    ).toBeNull()
    await userEvent.type(within(dialog).getByLabelText("Username"), "carol")
    await userEvent.type(within(dialog).getByLabelText("Full name"), "Carol C")
    await userEvent.type(
      within(dialog).getByLabelText("Initial password"),
      "start-pass-123"
    )
    await userEvent.selectOptions(role, "admin")
    await userEvent.click(within(dialog).getByLabelText("hr"))
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Create user" })
    )
    await waitFor(() =>
      expect(bodyOf(fetchMock, "POST", "/api/admin/users")).toEqual({
        username: "carol",
        full_name: "Carol C",
        password: "start-pass-123",
        role: "admin",
        group_ids: ["g1"],
      })
    )
  })
})
