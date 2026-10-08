"use client"

import { useEffect, useRef } from "react"

import { AssistantMessage } from "@/components/chat/assistant-message"
import type { UIMessage } from "@/lib/chat-state"
import type { SourceCard } from "@/lib/types"

export function MessageList({
  messages,
  onOpenSource,
}: {
  messages: UIMessage[]
  onOpenSource: (card: SourceCard) => void
}) {
  const endRef = useRef<HTMLDivElement>(null)
  const last = messages.at(-1)
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" })
  }, [messages.length, last?.content])

  return (
    <div
      className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-6"
      aria-live="polite"
    >
      {messages.map((m) =>
        m.role === "user" ? (
          <div
            key={m.id}
            className="ml-auto max-w-[80%] rounded-2xl bg-muted px-4 py-2 whitespace-pre-wrap"
          >
            {m.content}
          </div>
        ) : (
          <AssistantMessage
            key={m.id}
            message={m}
            onOpenSource={onOpenSource}
          />
        )
      )}
      <div ref={endRef} />
    </div>
  )
}
