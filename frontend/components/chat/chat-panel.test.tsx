import { QueryClient, useQuery } from "@tanstack/react-query"
import { act, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useState } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ChatPanel } from "@/components/chat/chat-panel"
import { CollectionSelectionProvider } from "@/components/chat/collection-selection"
import { api } from "@/lib/api"
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

const done = (content: string) =>
  [
    "done",
    {
      message_id: `m-${content}`,
      content,
      outcome: "answered",
      citations: [],
      low_confidence: false,
      trace_id: null,
    },
  ] as [string, unknown]

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
    expect(screen.queryByText("Could not reach the assistant.")).toBeNull()
    expect(screen.queryByText(/Unauthorized/)).toBeNull()
    expect(screen.queryByLabelText("Thinking")).toBeNull()
    expect(screen.getByPlaceholderText("Ask a question")).not.toBeDisabled()
  })

  it("aborts the stream and does not navigate when unmounted mid-answer", async () => {
    let controller!: ReadableStreamDefaultController<Uint8Array>
    const enc = new TextEncoder()
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        controller = c
      },
    })
    let chatSignal: AbortSignal | undefined
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (String(input) === "/api/collections") return jsonResponse([])
      chatSignal = init?.signal ?? undefined
      return new Response(body, {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      })
    })
    const { unmount } = renderWithProviders(
      <ChatPanel conversationId={null} initialMessages={[]} />
    )
    await userEvent.type(
      screen.getByPlaceholderText("Ask a question"),
      "Hi{Enter}"
    )
    await waitFor(() => expect(chatSignal).toBeDefined())
    controller.enqueue(
      enc.encode(
        'event: meta\ndata: {"conversation_id":"c9","user_message_id":"u1"}\n\n'
      )
    )
    unmount()
    expect(chatSignal!.aborted).toBe(true)
    try {
      controller.close()
    } catch {
      // already cancelled by the abort
    }
    await new Promise((r) => setTimeout(r, 50))
    expect(replace).not.toHaveBeenCalled()
  })

  it("drops the cached conversation after an answer so the next visit is fresh", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (String(input) === "/api/collections") return jsonResponse([])
      return sse(
        ["meta", { conversation_id: "c1", user_message_id: "u1" }],
        [
          "done",
          {
            message_id: "m2",
            content: "New answer.",
            outcome: "answered",
            citations: [],
            low_confidence: false,
            trace_id: null,
          },
        ]
      )
    })
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    client.setQueryData(["conversation", "c1"], { id: "c1", messages: [] })
    renderWithProviders(
      <ChatPanel conversationId="c1" initialMessages={[]} />,
      client
    )
    await userEvent.type(
      screen.getByPlaceholderText("Ask a question"),
      "Again{Enter}"
    )
    expect(await screen.findByText("New answer.")).toBeInTheDocument()
    await waitFor(() =>
      expect(client.getQueryData(["conversation", "c1"])).toBeUndefined()
    )
  })
  it("keeps the picked collections when a new chat moves to its conversation", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input) => {
        const url = String(input)
        if (url === "/api/collections")
          return jsonResponse([{ id: "k1", name: "HR", description: "" }])
        return sse(
          ["meta", { conversation_id: "c1", user_message_id: "u1" }],
          done("Answer.")
        )
      })
    // Stands in for the /app layout (provider) and the route (conversation id).
    let goTo!: (id: string) => void
    function Harness() {
      const [id, setId] = useState<string | null>(null)
      goTo = setId
      return (
        <CollectionSelectionProvider>
          <ChatPanel
            key={id ?? "new"}
            conversationId={id}
            initialMessages={[]}
          />
        </CollectionSelectionProvider>
      )
    }
    renderWithProviders(<Harness />)
    await userEvent.click(
      screen.getByRole("button", { name: /All collections/ })
    )
    await userEvent.click(
      await screen.findByRole("menuitemcheckbox", { name: "HR" })
    )
    await userEvent.keyboard("{Escape}")
    await userEvent.type(
      screen.getByPlaceholderText("Ask a question"),
      "First{Enter}"
    )
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/app/c/c1"))

    // The route change remounts the panel as the started conversation.
    act(() => goTo("c1"))
    expect(
      await screen.findByRole("button", { name: /HR/ })
    ).toBeInTheDocument()
    await userEvent.type(
      screen.getByPlaceholderText("Ask a question"),
      "Second{Enter}"
    )
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(([u]) => String(u) === "/api/chat")
      ).toHaveLength(2)
    )
    const bodies = fetchMock.mock.calls
      .filter(([u]) => String(u) === "/api/chat")
      .map(([, init]) => JSON.parse(String(init?.body)))
    expect(bodies[0].collection_ids).toEqual(["k1"])
    expect(bodies[1]).toEqual({
      question: "Second",
      collection_ids: ["k1"],
      conversation_id: "c1",
    })
  })

  it("stops waiting when the stream ends without done or error", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (String(input) === "/api/collections") return jsonResponse([])
      return sse(
        ["meta", { conversation_id: "c1", user_message_id: "u1" }],
        ["token", { text: "Partial" }]
      )
    })
    renderWithProviders(<ChatPanel conversationId="c1" initialMessages={[]} />)
    const box = screen.getByPlaceholderText("Ask a question")
    await userEvent.type(box, "Hi{Enter}")
    await waitFor(() => expect(box).not.toBeDisabled())
    expect(screen.queryByRole("button", { name: "Stop" })).toBeNull()
    expect(screen.queryByLabelText("Thinking")).toBeNull()
  })

  it("refetches an observed conversation instead of removing it", async () => {
    let conversationFetches = 0
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input)
      if (url === "/api/collections") return jsonResponse([])
      if (url === "/api/conversations/c1") {
        conversationFetches++
        return jsonResponse({ id: "c1", messages: [] })
      }
      return sse(
        ["meta", { conversation_id: "c1", user_message_id: "u1" }],
        done("Fresh.")
      )
    })
    function Observer() {
      useQuery({
        queryKey: ["conversation", "c1"],
        queryFn: () => api.conversation("c1"),
      })
      return null
    }
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    renderWithProviders(
      <>
        <Observer />
        <ChatPanel conversationId="c1" initialMessages={[]} />
      </>,
      client
    )
    await waitFor(() => expect(conversationFetches).toBe(1))
    await userEvent.type(
      screen.getByPlaceholderText("Ask a question"),
      "Again{Enter}"
    )
    expect(await screen.findByText("Fresh.")).toBeInTheDocument()
    await waitFor(() => expect(conversationFetches).toBe(2))
    expect(client.getQueryData(["conversation", "c1"])).toBeDefined()
  })
})
