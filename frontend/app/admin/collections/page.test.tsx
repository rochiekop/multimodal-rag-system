import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import CollectionsPage from "@/app/admin/collections/page"
import { jsonResponse, renderWithProviders } from "@/test/render"

const g1 = { id: "g1", name: "hr", description: "" }
const g2 = { id: "g2", name: "finance", description: "" }
const collection = {
  id: "c1",
  name: "Policies",
  description: "HR policies",
  sensitive: false,
  groups: [g1],
  created_at: "2026-10-01T00:00:00Z",
}

function mockApi() {
  return vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, init) => {
      const url = String(input)
      if (init?.method === "PATCH") return jsonResponse(collection)
      if (url === "/api/admin/groups") return jsonResponse([g1, g2])
      return jsonResponse([collection])
    })
}

const patches = (fetchMock: ReturnType<typeof mockApi>) =>
  fetchMock.mock.calls
    .filter(([, i]) => i?.method === "PATCH")
    .map(([, i]) => JSON.parse(String(i?.body)))

describe("CollectionsPage", () => {
  it("asks for a password only when groups change", async () => {
    const fetchMock = mockApi()
    renderWithProviders(<CollectionsPage />)
    await userEvent.click(
      await screen.findByRole("button", { name: "Edit Policies" })
    )
    let dialog = await screen.findByRole("dialog")
    await userEvent.click(within(dialog).getByLabelText("Sensitive"))
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }))
    await waitFor(() => expect(patches(fetchMock)).toHaveLength(1))
    expect(patches(fetchMock)[0]).toEqual({
      name: "Policies",
      description: "HR policies",
      sensitive: true,
    })

    await userEvent.click(screen.getByRole("button", { name: "Edit Policies" }))
    dialog = await screen.findByRole("dialog")
    await userEvent.click(within(dialog).getByLabelText("finance"))
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }))
    await userEvent.type(
      await screen.findByLabelText("Your password"),
      "pw-123"
    )
    await userEvent.click(screen.getByRole("button", { name: "Change access" }))
    await waitFor(() => expect(patches(fetchMock)).toHaveLength(2))
    expect(patches(fetchMock)[1]).toMatchObject({
      group_ids: ["g1", "g2"],
      password: "pw-123",
    })
  })
})
