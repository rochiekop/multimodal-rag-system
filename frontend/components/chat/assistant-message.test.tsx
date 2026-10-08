import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { AssistantMessage } from "@/components/chat/assistant-message"
import type { UIMessage } from "@/lib/chat-state"
import type { SourceCard } from "@/lib/types"
import { jsonResponse, renderWithProviders } from "@/test/render"

const card: SourceCard = {
  n: 1,
  doc_id: "d1",
  version_id: "v1",
  filename: "handbook.pdf",
  page: 3,
  bbox: { l: 10, t: 20, r: 110, b: 70 },
  page_image_scale: 1.5,
  heading_path: ["Leave"],
  modality: "text",
  score: 0.9,
  snippet: "Annual leave is 25 days.",
}

function message(overrides: Partial<UIMessage> = {}): UIMessage {
  return {
    id: "m1",
    role: "assistant",
    content: "Annual leave is **25 days** [1]. In [2024] too.",
    outcome: "answered",
    sources: [card],
    citations: [card],
    low_confidence: false,
    feedback_rating: null,
    feedback_comment: null,
    created_at: "",
    ...overrides,
  }
}

describe("AssistantMessage", () => {
  it("renders markdown with citation badges for real sources only", async () => {
    const onOpenSource = vi.fn()
    renderWithProviders(
      <AssistantMessage message={message()} onOpenSource={onOpenSource} />
    )
    expect(screen.getByText("25 days").tagName).toBe("STRONG")
    expect(screen.getByText(/In \[2024\] too/)).toBeInTheDocument()
    await userEvent.click(
      screen.getByRole("button", { name: "Source 1: handbook.pdf, page 3" })
    )
    expect(onOpenSource).toHaveBeenCalledWith(card)
  })

  it("sanitizes html in answers", () => {
    const { container } = renderWithProviders(
      <AssistantMessage
        message={message({
          content:
            'Hi <script>alert(1)</script><img src=x onerror="alert(2)"> there',
        })}
        onOpenSource={vi.fn()}
      />
    )
    expect(container.querySelector("script")).toBeNull()
    expect(container.querySelector("img[onerror]")).toBeNull()
  })

  it("does not render javascript: links", () => {
    const { container } = renderWithProviders(
      <AssistantMessage
        message={message({ content: "[click](javascript:alert(1))" })}
        onOpenSource={vi.fn()}
      />
    )
    for (const a of container.querySelectorAll("a")) {
      expect(a.getAttribute("href") ?? "").not.toMatch(/^javascript:/i)
    }
  })

  it("shows the low-confidence badge and the not-found closest matches", () => {
    renderWithProviders(
      <>
        <AssistantMessage
          message={message({ low_confidence: true })}
          onOpenSource={vi.fn()}
        />
        <AssistantMessage
          message={message({
            id: "m2",
            outcome: "not_found",
            citations: [],
            content: "I couldn't find this in the available documents.",
          })}
          onOpenSource={vi.fn()}
        />
      </>
    )
    expect(
      screen.getByText("Low confidence — verify sources")
    ).toBeInTheDocument()
    expect(screen.getByText("Closest matches")).toBeInTheDocument()
  })

  it("sends 👎 feedback with a comment", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(jsonResponse({ ...message(), feedback_rating: -1 }))
    renderWithProviders(
      <AssistantMessage message={message()} onOpenSource={vi.fn()} />
    )
    await userEvent.click(screen.getByRole("button", { name: "Bad answer" }))
    await userEvent.type(
      await screen.findByLabelText("What was wrong? (optional)"),
      "Outdated"
    )
    await userEvent.click(screen.getByRole("button", { name: "Send feedback" }))
    expect(fetchMock.mock.calls[0][0]).toBe("/api/messages/m1/feedback")
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      rating: -1,
      comment: "Outdated",
    })
  })

  it("hides feedback while streaming", () => {
    renderWithProviders(
      <AssistantMessage
        message={message({ id: "temp-1", streaming: true })}
        onOpenSource={vi.fn()}
      />
    )
    expect(screen.queryByRole("button", { name: "Bad answer" })).toBeNull()
  })
})
