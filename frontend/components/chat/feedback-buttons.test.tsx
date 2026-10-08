import { QueryClient, useQuery } from "@tanstack/react-query"
import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { FeedbackButtons } from "@/components/chat/feedback-buttons"
import { api } from "@/lib/api"
import { jsonResponse, renderWithProviders } from "@/test/render"

describe("FeedbackButtons", () => {
  it("drops unobserved transcripts and refetches the observed one", async () => {
    let activeFetches = 0
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input)
      if (url === "/api/conversations/active") {
        activeFetches++
        return jsonResponse({ id: "active", messages: [] })
      }
      return jsonResponse({ id: "m1", feedback_rating: 1 })
    })
    function Observer() {
      useQuery({
        queryKey: ["conversation", "active"],
        queryFn: () => api.conversation("active"),
      })
      return null
    }
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    client.setQueryData(["conversation", "old"], { id: "old", messages: [] })
    renderWithProviders(
      <>
        <Observer />
        <FeedbackButtons messageId="m1" initial={null} />
      </>,
      client
    )
    await waitFor(() => expect(activeFetches).toBe(1))
    await userEvent.click(screen.getByRole("button", { name: "Good answer" }))
    await waitFor(() => expect(activeFetches).toBe(2))
    expect(client.getQueryData(["conversation", "old"])).toBeUndefined()
    expect(client.getQueryData(["conversation", "active"])).toBeDefined()
  })
})
