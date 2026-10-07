import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ChatPanel } from "@/components/chat/chat-panel"
import { navigateTo } from "@/lib/navigate"
import { jsonResponse, renderWithProviders } from "@/test/render"

const replace = vi.fn()
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }))
vi.mock("@/lib/navigate", () => ({ navigateTo: vi.fn() }))

function sse(...events: [string, unknown][]): Response {
  const body = events
    .map(([e, d]) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`)
    .join("")
  return new Response(body, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  })
}

afterEach(() => vi.clearAllMocks())

describe("ChatPanel", () => {
  it("asks, streams and shows the final answer", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input) => {
        const url = String(input)
        if (url === "/api/collections")
          return jsonResponse([{ id: "k1", name: "HR", description: "" }])
        return sse(
          ["meta", { conversation_id: "c1", user_message_id: "u1" }],
          ["token", { text: "Twenty " }],
          [
            "done",
            {
              message_id: "m1",
              content: "Twenty days.",
              outcome: "answered",
              citations: [],
              low_confidence: false,
              trace_id: null,
            },
          ]
        )
      })
    renderWithProviders(
      <ChatPanel conversationId={null} initialMessages={[]} />
    )
    await userEvent.type(
      screen.getByPlaceholderText("Ask a question"),
      "How many days?{Enter}"
    )
    expect(await screen.findByText("Twenty days.")).toBeInTheDocument()
    expect(screen.getByText("How many days?")).toBeInTheDocument()
    const chatCall = fetchMock.mock.calls.find(
      ([u]) => String(u) === "/api/chat"
    )!
    expect(JSON.parse(String(chatCall[1]?.body))).toEqual({
      question: "How many days?",
      collection_ids: [],
    })
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/app/c/c1"))
  })

  it("shows a refusal from the server and allows asking again", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (String(input) === "/api/collections") return jsonResponse([])
      return jsonResponse(
        {
          detail: {
            code: "rate_limited",
            message: "You're sending questions too quickly. Wait a minute.",
          },
        },
        429
      )
    })
    renderWithProviders(
      <ChatPanel conversationId={null} initialMessages={[]} />
    )
    const box = screen.getByPlaceholderText("Ask a question")
    await userEvent.type(box, "Hi{Enter}")
    expect(
      await screen.findByText(/sending questions too quickly/)
    ).toBeInTheDocument()
    await waitFor(() => expect(box).not.toBeDisabled())
  })

  it("signs out when the chat request returns 401", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input) => {
        const url = String(input)
        if (url === "/api/collections") return jsonResponse([])
        if (url === "/api/auth/session") return jsonResponse(null, 204)
        return jsonResponse(
          { detail: { code: "unauthorized", message: "Unauthorized" } },
          401
        )
      })
    renderWithProviders(
      <ChatPanel conversationId={null} initialMessages={[]} />
    )
    await userEvent.type(
      screen.getByPlaceholderText("Ask a question"),
      "Hi{Enter}"
    )
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([u, init]) =>
            String(u) === "/api/auth/session" && init?.method === "DELETE"
        )
      ).toBe(true)
    )
    await waitFor(() => expect(navigateTo).toHaveBeenCalledWith("/login"))
  })
})
