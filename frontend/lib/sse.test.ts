import { describe, expect, it, vi } from "vitest"

import { parseSSE, streamChat } from "@/lib/sse"

function streamOf(
  ...chunks: (string | Uint8Array)[]
): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(
          typeof chunk === "string" ? encoder.encode(chunk) : chunk
        )
      }
      controller.close()
    },
  })
}

async function collect<T>(iterable: AsyncIterable<T>): Promise<T[]> {
  const out: T[] = []
  for await (const item of iterable) out.push(item)
  return out
}

describe("parseSSE", () => {
  it("parses events split across chunks and multi-byte characters", async () => {
    const bytes = new TextEncoder().encode(
      'event: token\ndata: {"text":"café"}\n\n'
    )
    const cut = bytes.indexOf(0xc3) + 1 // split inside the two-byte "é"
    const events = await collect(
      parseSSE(
        streamOf(
          "event: meta\nda",
          'ta: {"conversation_id":"c1"}\n',
          "\n",
          bytes.slice(0, cut),
          bytes.slice(cut)
        )
      )
    )
    expect(events).toEqual([
      { event: "meta", data: '{"conversation_id":"c1"}' },
      { event: "token", data: '{"text":"café"}' },
    ])
  })

  it("handles CRLF line endings, comments and a final event without blank line", async () => {
    const events = await collect(
      parseSSE(
        streamOf(
          ": keepalive\r\nevent: done\r\ndata: {}\r\n\r\nevent: x\ndata: 1"
        )
      )
    )
    expect(events).toEqual([
      { event: "done", data: "{}" },
      { event: "x", data: "1" },
    ])
  })
})

describe("parseSSE robustness", () => {
  it("handles CRLF split across chunks and lone CR endings", async () => {
    const events = await collect(
      parseSSE(streamOf("event: a\r", "\ndata: 1\r", "\n\r\n"))
    )
    expect(events).toEqual([{ event: "a", data: "1" }])
    const lone = await collect(parseSSE(streamOf("event: b\rdata: 2\r\r")))
    expect(lone).toEqual([{ event: "b", data: "2" }])
  })

  it("cancels the source when the consumer stops early", async () => {
    let cancelled = false
    const encoder = new TextEncoder()
    const source = new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(encoder.encode("event: a\ndata: 1\n\nevent: b\ndata: 2\n\n"))
      },
      cancel() {
        cancelled = true
      },
    })
    for await (const event of parseSSE(source)) {
      expect(event.event).toBe("a")
      break
    }
    expect(cancelled).toBe(true)
  })
})

describe("streamChat", () => {
  it("rejects a malformed data payload with bad_stream", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(streamOf("event: token\ndata: {oops\n\n"), { status: 200 })
    )
    await expect(collect(streamChat({ question: "q" }))).rejects.toMatchObject({
      code: "bad_stream",
    })
  })

  it("posts with the CSRF header and yields typed events", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(streamOf('event: token\ndata: {"text":"Hi"}\n\n'), {
        status: 200,
      })
    )
    const events = await collect(streamChat({ question: "q" }))
    expect(events).toEqual([{ event: "token", data: { text: "Hi" } }])
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/chat")
    expect(new Headers(init?.headers).get("X-CSRF-Protection")).toBe("1")
  })
})
