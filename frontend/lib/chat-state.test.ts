import { describe, expect, it } from "vitest"

import { chatReducer, initialChatState } from "@/lib/chat-state"
import type { ChatEvent, SourceCard } from "@/lib/types"

const card: SourceCard = {
  n: 1,
  doc_id: "d1",
  version_id: "v1",
  filename: "handbook.pdf",
  page: 1,
  bbox: { l: 1, t: 2, r: 3, b: 4 },
  page_image_scale: 1.5,
  heading_path: ["Leave"],
  modality: "text",
  score: 0.9,
  snippet: "Annual leave is 25 days.",
}

function ask() {
  return chatReducer(initialChatState(null, []), {
    type: "ask",
    question: "Leave?",
    tempId: "t1",
  })
}

describe("chatReducer", () => {
  it("streams an answer and replaces it with the final content", () => {
    let state = ask()
    expect(state.streaming).toBe(true)
    expect(state.messages.map((m) => m.role)).toEqual(["user", "assistant"])
    const events: ChatEvent[] = [
      { event: "meta", data: { conversation_id: "c1", user_message_id: "u1" } },
      { event: "sources", data: { sources: [card] } },
      { event: "token", data: { text: "Annual leave is " } },
      { event: "token", data: { text: "25 days [1] [9]" } },
      {
        event: "done",
        data: {
          message_id: "m1",
          content: "Annual leave is 25 days [1]",
          outcome: "answered",
          citations: [card],
          low_confidence: true,
          trace_id: null,
        },
      },
    ]
    for (const event of events)
      state = chatReducer(state, { type: "event", event, tempId: "t1" })
    expect(state.conversationId).toBe("c1")
    expect(state.streaming).toBe(false)
    const [question, answer] = state.messages
    expect(question.id).toBe("u1")
    expect(answer).toMatchObject({
      id: "m1",
      content: "Annual leave is 25 days [1]",
      outcome: "answered",
      low_confidence: true,
      streaming: false,
    })
    expect(answer.sources).toEqual([card])
  })

  it("records an error event", () => {
    const state = chatReducer(ask(), {
      type: "event",
      event: {
        event: "error",
        data: { code: "answer_failed", message: "Try again", message_id: "m2" },
      },
      tempId: "t1",
    })
    expect(state.messages[1]).toMatchObject({
      id: "m2",
      outcome: "error",
      content: "Try again",
    })
    expect(state.streaming).toBe(false)
  })

  it("shows a refusal from the server and allows asking again", () => {
    const state = chatReducer(ask(), {
      type: "fail",
      tempId: "t1",
      message: "Chat is locked",
    })
    expect(state.messages[1]).toMatchObject({
      outcome: "error",
      content: "Chat is locked",
    })
    expect(state.streaming).toBe(false)
  })

  it("keeps partial text when the user stops", () => {
    let state = chatReducer(ask(), {
      type: "event",
      event: { event: "token", data: { text: "Partial" } },
      tempId: "t1",
    })
    state = chatReducer(state, { type: "stopped", tempId: "t1" })
    expect(state.messages[1]).toMatchObject({
      content: "Partial",
      outcome: "cancelled",
    })
  })

  it("adds a strike notice to blocked answers", () => {
    const state = chatReducer(ask(), {
      type: "event",
      event: {
        event: "done",
        data: {
          message_id: "m3",
          content: "I can't help with that request.",
          outcome: "blocked",
          citations: [],
          low_confidence: false,
          trace_id: null,
          strikes: 2,
          strike_limit: 3,
          locked_until: null,
        },
      },
      tempId: "t1",
    })
    expect(state.messages[1].notice).toBe(
      "This request broke the usage policy (2 of 3 warnings)."
    )
  })
})
