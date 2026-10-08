import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { ConversationList } from "@/components/conversation-list"
import { SidebarProvider } from "@/components/ui/sidebar"
import { jsonResponse, renderWithProviders } from "@/test/render"

const push = vi.fn()
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => "/app",
}))

const conversations = [
  { id: "c1", title: "Leave policy", created_at: "", updated_at: "" },
  { id: "c2", title: "Parking", created_at: "", updated_at: "" },
]

function setup(
  fetchImpl: (url: string, init?: RequestInit) => Response,
  activeId = "c1"
) {
  const fetchMock = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, init) => fetchImpl(String(input), init))
  renderWithProviders(
    <SidebarProvider>
      <ConversationList activeId={activeId} />
    </SidebarProvider>
  )
  return fetchMock
}

describe("ConversationList", () => {
  it("lists conversations and searches", async () => {
    const fetchMock = setup((url) =>
      jsonResponse(url.includes("?q=") ? [conversations[0]] : conversations)
    )
    expect(
      await screen.findByRole("link", { name: "Leave policy" })
    ).toHaveAttribute("href", "/app/c/c1")
    expect(screen.getByRole("link", { name: "Parking" })).toBeInTheDocument()
    await userEvent.type(
      screen.getByPlaceholderText("Search conversations"),
      "leave"
    )
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([u]) => String(u) === "/api/conversations?q=leave"
        )
      ).toBe(true)
    )
    await waitFor(() =>
      expect(screen.queryByRole("link", { name: "Parking" })).toBeNull()
    )
  })

  it("renames and deletes a conversation", async () => {
    const fetchMock = setup((url, init) => {
      if (init?.method === "PATCH")
        return jsonResponse({ ...conversations[1], title: "Car park" })
      if (init?.method === "DELETE") return jsonResponse(null, 204)
      return jsonResponse(conversations)
    })
    const item = (await screen.findByRole("link", { name: "Parking" })).closest(
      "li"
    )!
    await userEvent.click(
      within(item).getByRole("button", { name: "Conversation actions" })
    )
    await userEvent.click(
      await screen.findByRole("menuitem", { name: "Rename" })
    )
    const input = await screen.findByLabelText("Title")
    await userEvent.clear(input)
    await userEvent.type(input, "Car park")
    await userEvent.click(screen.getByRole("button", { name: "Save" }))
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([, i]) => i?.method === "PATCH")).toBe(
        true
      )
    )
    const patch = fetchMock.mock.calls.find(([, i]) => i?.method === "PATCH")!
    expect(JSON.parse(String(patch[1]?.body))).toEqual({ title: "Car park" })

    await userEvent.click(
      within(item).getByRole("button", { name: "Conversation actions" })
    )
    await userEvent.click(
      await screen.findByRole("menuitem", { name: "Delete" })
    )
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }))
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([u, i]) =>
            i?.method === "DELETE" && String(u) === "/api/conversations/c2"
        )
      ).toBe(true)
    )
  })

  it("returns to /app after deleting the active conversation", async () => {
    push.mockClear()
    setup((url, init) =>
      init?.method === "DELETE"
        ? jsonResponse(null, 204)
        : jsonResponse(conversations)
    )
    const item = (
      await screen.findByRole("link", { name: "Leave policy" })
    ).closest("li")!
    await userEvent.click(
      within(item).getByRole("button", { name: "Conversation actions" })
    )
    await userEvent.click(
      await screen.findByRole("menuitem", { name: "Delete" })
    )
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }))
    await waitFor(() => expect(push).toHaveBeenCalledWith("/app"))
  })
})
