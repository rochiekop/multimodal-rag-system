import type { ChatEvent, DoneData, Message } from "@/lib/types"

export type UIMessage = Message & { streaming?: boolean; notice?: string }

export interface ChatState {
  conversationId: string | null
  messages: UIMessage[]
  streaming: boolean
}

export type ChatAction =
  | { type: "load"; conversationId: string | null; messages: Message[] }
  | { type: "ask"; question: string; tempId: string }
  | { type: "event"; event: ChatEvent; tempId: string }
  | { type: "fail"; message: string; tempId: string }
  | { type: "stopped"; tempId: string }

export function initialChatState(
  conversationId: string | null,
  messages: Message[]
): ChatState {
  return { conversationId, messages, streaming: false }
}

function blank(id: string, role: Message["role"], content: string): UIMessage {
  return {
    id,
    role,
    content,
    outcome: null,
    sources: [],
    citations: [],
    low_confidence: false,
    feedback_rating: null,
    feedback_comment: null,
    created_at: new Date().toISOString(),
  }
}

function strikeNotice(data: DoneData): string | undefined {
  if (data.strikes === undefined) return undefined
  const base = `This request broke the usage policy (${data.strikes} of ${data.strike_limit} warnings).`
  return data.locked_until
    ? `${base} Chat is locked until ${new Date(data.locked_until).toLocaleString()}.`
    : base
}

function updateAnswer(
  state: ChatState,
  tempId: string,
  change: (message: UIMessage) => UIMessage
): UIMessage[] {
  return state.messages.map((m) => (m.id === tempId ? change(m) : m))
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "load":
      return initialChatState(action.conversationId, action.messages)
    case "ask":
      return {
        ...state,
        streaming: true,
        messages: [
          ...state.messages,
          blank(`${action.tempId}-q`, "user", action.question),
          { ...blank(action.tempId, "assistant", ""), streaming: true },
        ],
      }
    case "stopped":
      return {
        ...state,
        streaming: false,
        messages: updateAnswer(state, action.tempId, (m) =>
          m.outcome
            ? m
            : {
                ...m,
                streaming: false,
                outcome: "cancelled",
              }
        ),
      }
    case "fail":
      return {
        ...state,
        streaming: false,
        messages: updateAnswer(state, action.tempId, (m) =>
          m.outcome
            ? m
            : {
                ...m,
                streaming: false,
                outcome: "error",
                content: action.message,
              }
        ),
      }
    case "event": {
      const { event, tempId } = action
      switch (event.event) {
        case "meta":
          return {
            ...state,
            conversationId: event.data.conversation_id,
            messages: state.messages.map((m) =>
              m.id === `${tempId}-q`
                ? { ...m, id: event.data.user_message_id }
                : m
            ),
          }
        case "sources":
          return {
            ...state,
            messages: updateAnswer(state, tempId, (m) => ({
              ...m,
              sources: event.data.sources,
            })),
          }
        case "token":
          return {
            ...state,
            messages: updateAnswer(state, tempId, (m) => ({
              ...m,
              content: m.content + event.data.text,
            })),
          }
        case "done":
          return {
            ...state,
            streaming: false,
            messages: updateAnswer(state, tempId, (m) => ({
              ...m,
              id: event.data.message_id,
              content: event.data.content,
              outcome: event.data.outcome,
              citations: event.data.citations,
              low_confidence: event.data.low_confidence,
              streaming: false,
              notice: strikeNotice(event.data),
            })),
          }
        case "error":
          return {
            ...state,
            streaming: false,
            messages: updateAnswer(state, tempId, (m) => ({
              ...m,
              id: event.data.message_id ?? m.id,
              content: event.data.message,
              outcome: "error",
              streaming: false,
            })),
          }
      }
    }
  }
  return state
}
