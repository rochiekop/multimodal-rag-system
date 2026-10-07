"use client"

import { useRouter } from "next/navigation"
import { useCallback, useState } from "react"

import {
  NEW_CHAT_KEY,
  useMoveCollectionSelection,
} from "@/components/chat/collection-selection"
import { Composer } from "@/components/chat/composer"
import { MessageList } from "@/components/chat/message-list"
import { SourceViewer } from "@/components/chat/source-viewer"
import { ScrollArea } from "@/components/ui/scroll-area"
import { useChat } from "@/hooks/use-chat"
import { APP_NAME } from "@/lib/config"
import type { Message, SourceCard } from "@/lib/types"

export function ChatPanel({
  conversationId,
  initialMessages,
}: {
  conversationId: string | null
  initialMessages: Message[]
}) {
  const router = useRouter()
  const moveSelection = useMoveCollectionSelection()
  // A new chat moves to its conversation URL once the first answer is complete,
  // keeping the collections picked for it.
  const onStarted = useCallback(
    (id: string) => {
      moveSelection(NEW_CHAT_KEY, id)
      router.replace(`/app/c/${id}`)
    },
    [router, moveSelection]
  )
  const chat = useChat(
    conversationId,
    initialMessages,
    conversationId ? undefined : onStarted
  )
  const [source, setSource] = useState<SourceCard | null>(null)
  return (
    <div className="flex h-full flex-col">
      <ScrollArea className="min-h-0 flex-1">
        {chat.messages.length === 0 ? (
          <div className="mx-auto flex max-w-3xl flex-col items-center gap-2 px-4 pt-[20vh] text-center">
            <h1 className="text-2xl font-semibold">{APP_NAME}</h1>
            <p className="text-muted-foreground">
              Ask about your company&apos;s documents. Answers cite their
              sources.
            </p>
          </div>
        ) : (
          <MessageList messages={chat.messages} onOpenSource={setSource} />
        )}
      </ScrollArea>
      <Composer
        selectionKey={conversationId ?? NEW_CHAT_KEY}
        streaming={chat.streaming}
        onAsk={chat.ask}
        onStop={chat.stop}
      />
      <SourceViewer card={source} onClose={() => setSource(null)} />
    </div>
  )
}
