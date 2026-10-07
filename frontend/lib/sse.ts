import { apiFetch, ApiError } from "@/lib/api"
import type { ChatEvent } from "@/lib/types"

export interface SSEMessage {
  event: string
  data: string
}

function parseBlock(block: string): SSEMessage | null {
  let event = "message"
  const data: string[] = []
  for (const line of block.split("\n")) {
    if (!line || line.startsWith(":")) continue
    const colon = line.indexOf(":")
    const field = colon === -1 ? line : line.slice(0, colon)
    let value = colon === -1 ? "" : line.slice(colon + 1)
    if (value.startsWith(" ")) value = value.slice(1)
    if (field === "event") event = value
    else if (field === "data") data.push(value)
  }
  return data.length ? { event, data: data.join("\n") } : null
}

/** Server-Sent Events from a byte stream; safe across chunk and UTF-8 boundaries. */
export async function* parseSSE(
  stream: ReadableStream<Uint8Array>
): AsyncGenerator<SSEMessage> {
  const reader = stream.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n")
      let index = buffer.indexOf("\n\n")
      while (index !== -1) {
        const message = parseBlock(buffer.slice(0, index))
        buffer = buffer.slice(index + 2)
        if (message) yield message
        index = buffer.indexOf("\n\n")
      }
    }
    buffer += decoder.decode().replace(/\r\n/g, "\n")
    const tail = parseBlock(buffer.trim())
    if (tail) yield tail
  } finally {
    reader.releaseLock()
  }
}

export interface ChatRequest {
  question: string
  conversation_id?: string
  collection_ids?: string[]
}

export async function* streamChat(
  body: ChatRequest,
  signal?: AbortSignal
): AsyncGenerator<ChatEvent> {
  const response = await apiFetch("/api/chat", {
    method: "POST",
    body: JSON.stringify(body),
    headers: { Accept: "text/event-stream" },
    signal,
  })
  if (!response.body)
    throw new ApiError(502, "no_stream", "The server sent no answer stream")
  for await (const message of parseSSE(response.body)) {
    yield { event: message.event, data: JSON.parse(message.data) } as ChatEvent
  }
}
